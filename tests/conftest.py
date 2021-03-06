"""
pytest configuration for obsplus
"""
import sys
from os.path import join, dirname, abspath
from pathlib import Path

import obsplus
import obspy
import pytest
from obsplus.datasets.dataloader import DataSet
from obsplus.utils import get_reference_time
from obspy.signal.invsim import corn_freq_2_paz

# path to the test directory
TEST_PATH = abspath(dirname(__file__))
# path to the package directory
PKG_PATH = dirname(TEST_PATH)
# path to the test data directory
TEST_DATA_PATH = join(TEST_PATH, "data")
# test data cache
TEST_DATA_CACHE = join(TEST_DATA_PATH, "cached")

# add the package path to sys.path so imports are from repo
sys.path.insert(0, PKG_PATH)

import mopy
import mopy.constants
from mopy.core import SpectrumGroup


@pytest.fixture(scope="session", autouse=True)
def turn_on_debugging():
    """ Set the global debug flag to True. """
    mopy.constants.DEBUG = True


class CoalNodeDataset(DataSet):
    """ A dataset for the test coal node data. """

    base_path = Path(TEST_DATA_PATH)
    name = "node_dataset"

    def download_stations(self) -> None:
        pass


# --- Fixtures for crandall canyon DS


@pytest.fixture(scope="session")
def crandall_ds():
    return obsplus.load_dataset("crandall")


@pytest.fixture(scope="session")
def crandall_catalog(crandall_ds):
    """ Return the crandall catalog. Add one P amplitude first. """
    cat = crandall_ds.event_client.get_events()
    # create dict of origin times/eids
    ot_id = {get_reference_time(eve).timestamp: eve for eve in cat}
    min_time = min(ot_id)
    event = ot_id[min_time]
    # add noise time amplitudes for a few channels (just so noise spectra
    path = Path(TEST_DATA_PATH) / "crandall_noise_picks.xml"
    noisey_cat = obspy.read_events(str(path), "quakeml")
    event.picks.extend(noisey_cat[0].picks)
    event.amplitudes.extend(noisey_cat[0].amplitudes)
    return cat


@pytest.fixture(scope="session")
def crandall_event(crandall_catalog):
    """ Return the fore-shock of the crandall collapse. """
    endtime = obspy.UTCDateTime("2007-08-06T08")
    cat = crandall_catalog.get_events(endtime=endtime)
    assert len(cat) == 1, "there should only be one foreshock"
    return cat[0]


@pytest.fixture(scope="session")
def crandall_inventory(crandall_ds):
    """ Return the inventory for the crandall dataset."""
    return crandall_ds.station_client.get_stations()


@pytest.fixture(scope="session")
def crandall_stream(crandall_event, crandall_ds, crandall_inventory):
    """ Return the streams from the crandall event, remove response """
    time = obsplus.get_reference_time(crandall_event)
    t1 = time - 5
    t2 = time + 60
    st = crandall_ds.waveform_client.get_waveforms(starttime=t1, endtime=t2)
    st.detrend("linear")
    prefilt = [0.1, 0.2, 40, 50]
    st.remove_response(crandall_inventory, pre_filt=prefilt, output="VEL")
    return st


@pytest.fixture(scope="session")
def crandall_st_dict_unified(crandall_ds, crandall_inventory):
    """
    Return a stream dict for the crandal dataset where each stream has been
    re-sampled to 100 Hz
    """
    fetcher = crandall_ds.get_fetcher()
    st_dict = dict(fetcher.get_event_waveforms(time_before=10, time_after=190))
    # re-sample all traces to 100 Hz
    for _, st in st_dict.items():
        st.resample(40)
        st.detrend("linear")
        prefilt = [0.1, 0.2, 40, 50]
        st.remove_response(crandall_inventory, pre_filt=prefilt, output="DISP")
    # remove response
    return st_dict


@pytest.fixture(scope="session")
def crandall_source(crandall_event, crandall_stream, crandall_inventory):
    """ Return a Source instance for the crandall data. """
    source = mopy.Source(
        event=crandall_event, stream=crandall_stream, inventory=crandall_inventory
    )
    return source


@pytest.fixture(scope="session")
def source_group_crandall(request):
    """ Init a big source object on crandall data. """
    cache_path = Path(TEST_DATA_CACHE) / "crandall_source_group.pkl"
    if not cache_path.exists():
        crandall_st_dict_unified = request.getfixturevalue("crandall_st_dict_unified")
        crandall_catalog = request.getfixturevalue("crandall_catalog")
        crandall_inventory = request.getfixturevalue("crandall_inventory")
        sg = SpectrumGroup(
            crandall_st_dict_unified, crandall_catalog, crandall_inventory
        )
        sg.to_pickle(cache_path)
    else:
        sg = SpectrumGroup.from_pickle(cache_path)
    assert not hasattr(sg.stats, "process") or not sg.stats.processing
    assert not (sg.data == 0).all().all()
    return sg


# ------- Fixtures for Coal Node dataset


@pytest.fixture(scope="session")
def node_dataset():
    """ Return a dataset of the node data. """
    return obsplus.load_dataset('coal_node')


@pytest.fixture(scope="session")
def node_st_dict(node_dataset):
    """ Get the node dataset. """

    def remove_response(stt) -> obspy.Stream:
        """ using the fairfield files, remove the response through deconvolution """
        stt.detrend("linear")
        paz_5hz = corn_freq_2_paz(5.0, damp=0.707)
        paz_5hz["sensitivity"] = 76700
        pre_filt = (0.25, 0.5, 200.0, 250.0)
        stt.simulate(paz_remove=paz_5hz, pre_filt=pre_filt)
        return stt

    fetcher = node_dataset.get_fetcher()
    out = {}
    for eid, st in fetcher.yield_event_waveforms(time_before=10, time_after=10):
        out[eid] = remove_response(st)

    return out


@pytest.fixture(scope="session")
def node_catalog(node_dataset):
    """ return the node catalog. """
    return node_dataset.event_client.get_events()


@pytest.fixture(scope="session")
def node_inventory(node_dataset):
    """ get the inventory of the ndoe dataset. """
    return node_dataset.station_client.get_stations()


@pytest.fixture(scope="session")
def node_channel_info(node_st_dict, node_catalog, node_inventory):
    """ Return a channel info object from the node dataset. """
    kwargs = dict(st_dict=node_st_dict, catalog=node_catalog, inventory=node_inventory)
    return mopy.ChannelInfo(**kwargs)


@pytest.fixture(scope="session")
def node_trace_group(node_channel_info):
    """ Return a trace group from the node data. """
    return mopy.TraceGroup(node_channel_info)


@pytest.fixture(scope="session")
def source_group_node_session(node_trace_group):
    """ Return a source group with node data. """
    sg = mopy.SpectrumGroup(node_trace_group)
    assert not hasattr(sg.stats, "process") or not sg.stats.processing
    assert not (sg.data == 0).all().all()
    return sg


@pytest.fixture
def source_group_node(source_group_node_session):
    """ Get the source group, retrun copy for possible mutation. """
    return source_group_node_session.copy()


# --- collect all source groups


@pytest.fixture
def source_group(source_group_crandall):
    return source_group_crandall.copy()
