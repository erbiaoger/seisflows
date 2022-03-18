#!/usr/bin/env python
"""
This is the main seisflows.preprocess.base

This is a main Seisflows class, it controls the preprocessing.
"""
import os
import sys
import obspy
import logging
import numpy as np

from seisflows3.tools import msg
from seisflows3.tools import signal, unix
from seisflows3.config import custom_import
from seisflows3.tools.err import ParameterError
from seisflows3.tools.wrappers import exists, getset
from seisflows3.plugins import adjoint, misfit, readers, writers
from seisflows3.config import SeisFlowsPathsParameters

PAR = sys.modules["seisflows_parameters"]
PATH = sys.modules["seisflows_paths"]


class Default(custom_import("preprocess", "base")):
    """
    Default SeisFlows preprocessing class

    Provides data processing functions for seismic traces, with options for
    data misfit, filtering, normalization and muting
    """
    # Class-specific logger accessed using self.logger
    logger = logging.getLogger(__name__).getChild(__qualname__)

    def __init__(self):
        """
        These parameters should not be set by __init__!
        Attributes are just initialized as NoneTypes for clarity and docstrings
        """
        super().__init__()
        self.misfit = None
        self.adjoint = None
        self.reader = None
        self.writer = None

    @property
    def required(self):
        """
        A hard definition of paths and parameters required by this class,
        alongside their necessity for the class and their string explanations.
        """
        sf = SeisFlowsPathsParameters()

        # Define the Parameters required by this module
        sf.par("MISFIT", required=False, default="waveform", par_type=str,
               docstr="Misfit function for waveform comparisons, for available "
                      "see seisflows.plugins.misfit")

        sf.par("BACKPROJECT", required=False, default="null", par_type=str,
               docstr="Backprojection function for migration, for available "
                      "see seisflows.plugins.adjoint")

        sf.par("NORMALIZE", required=False, default="null", par_type=str,
               docstr="Data normalization option")

        sf.par("FILTER", required=False, default="null", par_type=str,
               docstr="Data filtering type, available options are:"
                      "BANDPASS (req. MIN/MAX PERIOD/FREQ);"
                      "LOWPASS (req. MAX_FREQ or MIN_PERIOD); "
                      "HIGHPASS (req. MIN_FREQ or MAX_PERIOD) ")

        sf.par("MIN_PERIOD", required=False, par_type=float,
               docstr="Minimum filter period applied to time series."
                      "See also MIN_FREQ, MAX_FREQ, if User defines FREQ "
                      "parameters, they will overwrite PERIOD parameters.")

        sf.par("MAX_PERIOD", required=False, par_type=float,
               docstr="Maximum filter period applied to time series."
                      "See also MIN_FREQ, MAX_FREQ, if User defines FREQ "
                      "parameters, they will overwrite PERIOD parameters.")

        sf.par("MIN_FREQ", required=False, par_type=float,
               docstr="Maximum filter frequency applied to time series."
                      "See also MIN_PERIOD, MAX_PERIOD, if User defines FREQ "
                      "parameters, they will overwrite PERIOD parameters.")

        sf.par("MAX_FREQ", required=False, par_type=float,
               docstr="Maximum filter frequency applied to time series,"
                      "See also MIN_PERIOD, MAX_PERIOD, if User defines FREQ "
                      "parameters, they will overwrite PERIOD parameters.")

        sf.par("MUTE", required=False, par_type=list, default=[],
               docstr="Data mute parameters used to zero out early / late "
                      "arrivals or offsets. Choose any number of: "
                      "EARLYARRIVALS: "

        return sf

    def check(self, validate=True):
        """ 
        Checks parameters and paths
        """
        self.logger.debug(msg.check(type(self)))

        if validate:
            self.required.validate()

        # Data normalization option
        if PAR.NORMALIZE:
            self.check_normalize_parameters()

        # Data muting option
        if PAR.MUTE:
            self.check_mute_parameters()

        # Data filtering options that will be passed to ObsPy filters
        if PAR.FILTER:
            acceptable_filters = ["BANDPASS", "LOWPASS", "HIGHPASS"]
            assert PAR.FILTER.upper() in acceptable_filters, \
                f"PAR.FILTER must be in {acceptable_filters}"

            # Set the min/max frequencies and periods, frequency takes priority
            if PAR.MIN_FREQ is not None:
                PAR.MAX_PERIOD = 1 / PAR.MIN_FREQ
            elif PAR.MAX_PERIOD is not None:
                PAR.MIN_FREQ = 1 / PAR.MAX_PERIOD

            if PAR.MAX_FREQ is not None:
                PAR.MIN_PERIOD = 1 / PAR.MAX_FREQ
            elif PAR.MIN_PERIOD is not None:
                PAR.MAX_FREQ = 1 / PAR.MIN_PERIOD

            # Check that the correct filter bounds have been set
            if PAR.FILTER.upper() == "BANDPASS":
                assert(PAR.MIN_FREQ is not None and PAR.MAX_FREQ is not None), \
                    ("BANDPASS filter PAR.MIN_PERIOD and PAR.MAX_PERIOD or " 
                     "PAR.MIN_FREQ and PAR.MAX_FREQ")
            elif PAR.FILTER.upper() == "LOWPASS":
                assert(PAR.MAX_FREQ is not None or PAR.MIN_PERIOD is not None),\
                    "LOWPASS requires PAR.MAX_FREQ or PAR.MIN_PERIOD"
            elif PAR.FILTER.upper() == "HIGHPASS":
                assert(PAR.MIN_FREQ is not None or PAR.MAX_PERIOD is not None),\
                    "HIGHPASS requires PAR.MIN_FREQ or PAR.MAX_PERIOD"

            # Check that filter bounds make sense
            if PAR.MIN_FREQ is not None:
                assert(PAR.MIN_FREQ > 0), "Minimum frequency must be > 0"
            if (PAR.MIN_FREQ is not None) and (PAR.MAX_FREQ is not None):
                assert(PAR.MIN_FREQ < PAR.MAX_FREQ), \
                    "Minimum frequency must be less than maximum frequency"
            if PAR.MAX_FREQ is not None:
                assert(PAR.MAX_FREQ < np.inf), "Maximum frequency must be < inf"

        # Assert that readers and writers available
        if PAR.FORMAT not in dir(readers):
            print(msg.ReaderError)
            raise ParameterError()

        if PAR.FORMAT not in dir(writers):
            print(msg.WriterError)
            raise ParameterError()

        # Assert that either misfit or backproject exists 
        if PAR.WORKFLOW.upper() == "INVERSION" and not PAR.MISFIT:
            # !!! Need a better error here
            raise ParameterError("PAR.MISFIT must be set w/ default preprocess")

    def setup(self):
        """
        Sets up data preprocessing machinery
        """
        self.logger.debug(msg.setup(type(self)))

        # Define misfit function and adjoint trace generator
        if PAR.MISFIT:
            self.logger.debug(f"misfit function is: '{PAR.MISFIT}'")
            self.misfit = getattr(misfit, PAR.MISFIT.lower())
            self.adjoint = getattr(adjoint, PAR.MISFIT.lower())
        elif PAR.BACKPROJECT:
            self.logger.debug(f"backproject function is: '{PAR.BACKPROJECT}'")
            self.adjoint = getattr(adjoint, PAR.BACKPROJECT.lower())

        # Define seismic data reader and writer
        self.reader = getattr(readers, PAR.FORMAT)
        self.writer = getattr(writers, PAR.FORMAT)

    def prepare_eval_grad(self, cwd="./", **kwargs):
        """
        Prepares solver for gradient evaluation by writing residuals and
        adjoint traces

        :type cwd: str
        :param cwd: current specfem working directory containing observed and 
            synthetic seismic data to be read and processed
        """
        # Need to load solver mid-workflow as preprocess is loaded first
        solver = sys.modules["seisflows_solver"]

        if solver.taskid == 0:
            self.logger.debug("preparing files for gradient evaluation")

        for filename in solver.data_filenames:
            obs = self.reader(path=os.path.join(cwd, "traces", "obs"),
                              filename=filename)
            syn = self.reader(path=os.path.join(cwd, "traces", "syn"), 
                              filename=filename)

            # Process observations and synthetics identically
            if PAR.FILTER:
                if solver.taskid == 0:
                    self.logger.debug(f"applying {PAR.FILTER} filter to data")
                obs = self.apply_filter(obs)
                syn = self.apply_filter(syn)
            if PAR.MUTE:
                if solver.taskid == 0:
                    self.logger.debug(f"applying {PAR.MUTE} mute to data")
                obs = self.apply_mute(obs)
                syn = self.apply_mute(syn)
            if PAR.NORMALIZE:
                if solver.taskid == 0:
                    self.logger.debug(f"normalizing {PAR.NORMALIZE} data")
                obs = self.apply_normalize(obs)
                syn = self.apply_normalize(syn)

            if PAR.MISFIT is not None:
                self.write_residuals(cwd, syn, obs)

            # Write the adjoint traces. Rename file extension for Specfem
            if PAR.FORMAT.upper() == "ASCII":
                # Change the extension to '.adj' from whatever it is
                ext = os.path.splitext(filename)[-1]
                filename_out = filename.replace(ext, ".adj")
            elif PAR.FORMAT.upper() == "SU":
                raise NotImplementedError

            self.write_adjoint_traces(path=os.path.join(cwd, "traces", "adj"),
                                      syn=syn, obs=obs, filename=filename_out)

        # Copy over the STATIONS file to STATIONS_ADJOINT required by Specfem
        # ASSUMING that all stations are used in adjoint simulation
        src = os.path.join(cwd, "DATA", "STATIONS")
        dst = os.path.join(cwd, "DATA", "STATIONS_ADJOINT")
        unix.cp(src, dst)

    def write_residuals(self, path, syn, obs):
        """
        Computes residuals between observed and synthetic seismogram based on
        the misfit function PAR.MISFIT. Saves the residuals for each 
        data-synthetic pair into a text file located at: 
        
        ./scratch/solver/*/residuals

        The resulting file will be a single-column ASCII file that needs to be
        summed before use by the solver

        :type path: str
        :param path: location "adjoint traces" will be written
        :type syn: obspy.core.stream.Stream
        :param syn: synthetic data
        :type obs: obspy.core.stream.Stream
        :param syn: observed data
        """
        nt, dt, _ = self.get_time_scheme(syn)
        nn, _ = self.get_network_size(syn)

        residuals = []
        for ii in range(nn):
            residuals.append(self.misfit(syn[ii].data, obs[ii].data, nt, dt))

        filename = os.path.join(path, "residuals")
        if exists(filename):
            residuals = np.append(residuals, np.loadtxt(filename))

        np.savetxt(filename, residuals)

    def sum_residuals(self, files):
        """
        Sums squares of residuals

        :type files: str
        :param files: list of single-column text files containing residuals
        :rtype: float
        :return: sum of squares of residuals
        """
        total_misfit = 0.
        for filename in files:
            total_misfit += np.sum(np.loadtxt(filename) ** 2.)

        return total_misfit

    def write_adjoint_traces(self, path, syn, obs, filename):
        """
        Writes "adjoint traces" required for gradient computation

        :type path: str
        :param path: location "adjoint traces" will be written
        :type syn: obspy.core.stream.Stream
        :param syn: synthetic data
        :type obs: obspy.core.stream.Stream
        :param syn: observed data
        :type channel: str
        :param channel: channel or component code used by writer
        """
        nt, dt, _ = self.get_time_scheme(syn)
        nn, _ = self.get_network_size(syn)

        adj = syn
        for ii in range(nn):
            adj[ii].data = self.adjoint(syn[ii].data, obs[ii].data, nt, dt)

        self.writer(adj, path, filename)

    def apply_filter(self, st):
        """
        Apply a filter to waveform data using ObsPy

        :type st: obspy.core.stream.Stream
        :param st: stream to be filtered
        :rtype: obspy.core.stream.Stream
        :return: filtered traces
        """
        # Pre-processing before filtering
        st.detrend("demean")
        st.detrend("linear")
        st.taper(0.05, type="hann")

        if PAR.FILTER.upper() == "BANDPASS":
            st.filter("bandpass", zerophase=True, freqmin=PAR.MIN_FREQ,
                      freqmax=PAR.FREQMAX)
        elif PAR.FILTER.upper() == "LOWPASS":
            st.filter("lowpass", zerophase=True, freq=PAR.MAX_FREQ)
        elif PAR.FILTER.upper() == "HIGHPASS":
            st.filter("highpass", zerophase=True, freq=PAR.MIN_FREQ)

        return st

    def apply_mute(self, st):
        """
        Apply mute on data

        :type st: obspy.core.stream.Stream
        :param st: stream to mute
        :return:
        """
        if not PAR.MUTE:
            return st

        if 'MuteEarlyArrivals' in PAR.MUTE:
            traces = signal.mute_early_arrivals(
                st,
                PAR.MUTE_EARLY_ARRIVALS_SLOPE,  # (units: time/distance)
                PAR.MUTE_EARLY_ARRIVALS_CONST,  # (units: time)
                self.get_time_scheme(st),
                self.get_source_coords(st),
                self.get_receiver_coords(st))

        if 'MuteLateArrivals' in PAR.MUTE:
            traces = signal.mute_late_arrivals(
                st,
                PAR.MUTE_LATE_ARRIVALS_SLOPE,  # (units: time/distance)
                PAR.MUTE_LATE_ARRIVALS_CONST,  # (units: time)
                self.get_time_scheme(st),
                self.get_source_coords(st),
                self.get_receiver_coords(st))

        if 'MuteShortOffsets' in PAR.MUTE:
            traces = signal.mute_short_offsets(
                st,
                PAR.MUTE_SHORT_OFFSETS_DIST,
                self.get_source_coords(st),
                self.get_receiver_coords(st))

        if 'MuteLongOffsets' in PAR.MUTE:
            traces = signal.mute_long_offsets(
                st,
                PAR.MUTE_LONG_OFFSETS_DIST,
                self.get_source_coords(st),
                self.get_receiver_coords(st))

        return traces

    def apply_normalize(self, traces):
        """
        Normalize the amplitudes of the waveforms
        :param traces:
        :return:
        """
        if not PAR.NORMALIZE:
            return traces

        if 'NormalizeEventsL1' in PAR.NORMALIZE:
            # normalize event by L1 norm of all traces
            w = 0.
            for tr in traces:
                w += np.linalg.norm(tr.data, ord=1)
            for tr in traces:
                tr.data /= w

        elif 'NormalizeEventsL2' in PAR.NORMALIZE:
            # normalize event by L2 norm of all traces
            w = 0.
            for tr in traces:
                w += np.linalg.norm(tr.data, ord=2)
            for tr in traces:
                tr.data /= w

        if 'NormalizeTracesL1' in PAR.NORMALIZE:
            # normalize each trace by its L1 norm
            for tr in traces:
                w = np.linalg.norm(tr.data, ord=1)
                if w > 0:
                    tr.data /= w

        elif 'NormalizeTracesL2' in PAR.NORMALIZE:
            # normalize each trace by its L2 norm
            for tr in traces:
                w = np.linalg.norm(tr.data, ord=2)
                if w > 0:
                    tr.data /= w

        return traces

    def apply_filter_backwards(self, traces):
        """

        :param traces:
        :return:
        """
        for tr in traces:
            tr.data = np.flip(tr.data)

        traces = self.apply_filter()

        for tr in traces:
            tr.data = np.flip(tr.data)

        return traces

    def check_mute_parameters(self):
        """
        Checks mute settings, which are used to zero out early or late arrivals
        or offsets
        """
        assert getset(PAR.MUTE) <= {'MuteEarlyArrivals',
                                    'MuteLateArrivals',
                                    'MuteShortOffsets',
                                    'MuteLongOffsets'}

        if 'MuteEarlyArrivals' in PAR.MUTE:
            assert 'MUTE_EARLY_ARRIVALS_SLOPE' in PAR
            assert 'MUTE_EARLY_ARRIVALS_CONST' in PAR
            assert PAR.MUTE_EARLY_ARRIVALS_SLOPE >= 0.

        if 'MuteLateArrivals' in PAR.MUTE:
            assert 'MUTE_LATE_ARRIVALS_SLOPE' in PAR
            assert 'MUTE_LATE_ARRIVALS_CONST' in PAR
            assert PAR.MUTE_LATE_ARRIVALS_SLOPE >= 0.

        if 'MuteShortOffsets' in PAR.MUTE:
            assert 'MUTE_SHORT_OFFSETS_DIST' in PAR
            assert 0 < PAR.MUTE_SHORT_OFFSETS_DIST

        if 'MuteLongOffsets' in PAR.MUTE:
            assert 'MUTE_LONG_OFFSETS_DIST' in PAR
            assert 0 < PAR.MUTE_LONG_OFFSETS_DIST

        if 'MuteShortOffsets' not in PAR.MUTE:
            setattr(PAR, 'MUTE_SHORT_OFFSETS_DIST', 0.)

        if 'MuteLongOffsets' not in PAR.MUTE:
            setattr(PAR, 'MUTE_LONG_OFFSETS_DIST', 0.)

    def check_normalize_parameters(self):
        """
        Check that the normalization parameters are properly set
        """
        assert getset(PAR.NORMALIZE) < {'NormalizeTracesL1',
                                        'NormalizeTracesL2',
                                        'NormalizeEventsL1',
                                        'NormalizeEventsL2'}

    def get_time_scheme(self, traces):
        """
        FIXME: extract time scheme from trace headers rather than parameters

        :param traces:
        :return:
        """
        nt = PAR.NT
        dt = PAR.DT
        t0 = 0.
        return nt, dt, t0

    def get_network_size(self, traces):
        """

        :param traces:
        :return:
        """
        nrec = len(traces)
        nsrc = 1
        return nrec, nsrc

    def get_receiver_coords(self, st):
        """
        Retrieve the coordinates from a Stream object

        :type st: obspy.core.stream.Stream
        :param st: a stream to query for coordinates
        :return:
        """
        if PAR.FORMAT.upper == "SU":
            rx, ry, rz = [], [], []

            for tr in st:
                rx += [tr.stats.su.trace_header.group_coordinate_x]
                ry += [tr.stats.su.trace_header.group_coordinate_y]
                rz += [0.]
            return rx, ry, rz
        else:
            raise NotImplementedError

    def get_source_coords(self, st):
        """
        Get the coordinates of the source object

        :type st: obspy.core.stream.Stream
        :param st: a stream to query for coordinates
        :return:
        """
        if PAR.FORMAT.upper() == "SU":
            sx, sy, sz = [], [], []
            for tr in st:
                sx += [tr.stats.su.trace_header.source_coordinate_x]
                sy += [tr.stats.su.trace_header.source_coordinate_y]
                sz += [0.]
            return sx, sy, sz
        else:
            raise NotImplementedError
    
    def finalize(self):
        """
        Any finalization processes that need to take place at the end of an iter
        """
        pass
