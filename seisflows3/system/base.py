#!/usr/bin/env python
"""
This is the base class seisflows.system.Base
This class provides the core utilities interaction with HPC systems which must
be overloaded by subclasses
"""
import os
import sys
import logging
from glob import glob

from seisflows3.tools import unix, msg
from seisflows3.config import save, saveobj, SeisFlowsPathsParameters


PAR = sys.modules['seisflows_parameters']
PATH = sys.modules['seisflows_paths']


class Base:
    """
    Abstract base class for the Systems module which controls interaction with
    compute systems such as HPC clusters.
    """
    # Class-specific logger accessed using self.logger
    logger = logging.getLogger(__name__).getChild(__qualname__)

    @property
    def required(self):
        """
        A hard definition of paths and parameters required by this class,
        alongside their necessity for the class and their string explanations.
        """
        sf = SeisFlowsPathsParameters()

        # Define the Parameters required by this module
        sf.par("TITLE", required=False,
               default=os.path.basename(os.path.abspath(".")), par_type=str,
               docstr="The name used to submit jobs to the system, defaults "
                      "to the name of the working directory")

        sf.par("WALLTIME", required=True, par_type=float,
               docstr="Maximum job time in minutes for main SeisFlows3 job")

        sf.par("TASKTIME", required=True, par_type=float,
               docstr="Maximum job time in minutes for each SeisFlows3 task")

        sf.par("NTASK", required=True, par_type=int,
               docstr="Number of separate, individual tasks. Also equal to "
                      "the number of desired sources in workflow")

        sf.par("NPROC", required=True, par_type=int,
               docstr="Number of processor to use for each simulation")

        sf.par("PRECHECK", required=False, par_type=list,
               default=["TITLE", "BEGIN", "END", "WALLTIME"],
               docstr="A list of parameters that will be displayed to stdout "
                      "before 'submit' or 'resume' is run. Useful for "
                      "manually reviewing important parameters prior to "
                      "system submission")

        sf.par("LOG_LEVEL", required=False, par_type=str, default="DEBUG",
               docstr="Verbosity output of SF3 logger. Available from least to "
                      "most verbosity: 'CRITICAL', 'WARNING', 'INFO', 'DEBUG'; "
                      "defaults to 'DEBUG'")

        sf.par("VERBOSE", required=False, default=True, par_type=bool,
               docstr="Level of verbosity provided to the output log. If True, "
                      "log statements will declare what module/class/function "
                      "they are being called from. Useful for debugging but "
                      "also very noisy.")

        # Define the Paths required by this module
        # note: PATH.WORKDIR has been set by the entry point seisflows.setup()
        sf.path("SCRATCH", required=False,
                default=os.path.join(PATH.WORKDIR, "scratch"),
                docstr="scratch path to hold temporary data during workflow")

        sf.path("OUTPUT", required=False,
                default=os.path.join(PATH.WORKDIR, "output"),
                docstr="directory to save workflow outputs to disk")

        sf.path("SYSTEM", required=False,
                default=os.path.join(PATH.WORKDIR, "scratch", "system"),
                docstr="scratch path to hold any system related data")

        sf.path("LOCAL", required=False,
                docstr="path to local data to be used during workflow")

        sf.path("LOG", required=False, 
                default=os.path.join(PATH.WORKDIR, "output_seisflows3.txt"),
                docstr="path to write log statements to. defaults to "
                       "'output_seisflows3.txt'")

        return sf

    def check(self, validate=True):
        """
        Checks parameters and paths
        """
        msg.check(type(self))

        if validate:
            self.required.validate()

    def setup(self):
        """
        Create the SeisFlows3 directory structure in preparation for a
        SeisFlows3 workflow. Ensure that if any config information is left over
        from a previous workflow, that these files are not overwritten by
        the new workflow. Should be called by submit()

        .. note::
            This function is expected to create dirs: SCRATCH, SYSTEM, OUTPUT
            and the following log files: output, error

        :rtype: tuple of str
        :return: (path to output log, path to error log)
        """
        msg.setup(type(self))

        # Create scratch directories
        unix.mkdir(PATH.SCRATCH)
        unix.mkdir(PATH.SYSTEM)

        # Create output directories
        unix.mkdir(PATH.OUTPUT)
        log_files = os.path.join(PATH.WORKDIR, "logs")
        old_logs = os.path.join(log_files, "previous")
        unix.mkdir(log_files)
        unix.mkdir(old_logs)

        output_log = PATH.LOG
        error_log = os.path.join(PATH.WORKDIR, "error_log.txt")

        # If resuming, move old log files to keep them out of the way
        for log in [output_log, error_log]:
            unix.mv(src=glob(os.path.join(f"{log}*.txt")), dst=old_logs)

        # Copy the parameter.yaml file into the log directoroy
        par_copy = f"parameters_{PAR.BEGIN}-{PAR.END}.yaml"
        unix.cp(src="parameters.yaml",
                dst=os.path.join(log_files, par_copy)
                )

        return output_log, error_log

    def submit(self):
        """
        Main insertion point of SeisFlows3 onto the compute system.

        .. rubric::
            $ seisflows submit

        .. note::
            The expected behavior of the submit() function is to:
            1) run system setup, creating directory structure,
            2) execute workflow by submitting workflow.main()
        """
        raise NotImplementedError('Must be implemented by subclass.')

    def run(self, classname, method, *args, **kwargs):
        """
        Runs a task multiple times in parallel

        .. note::
            The expected behavior of the run() function is to: submit N jobs to
            the system in parallel. For example, in a simulation step, run()
            submits N jobs to the compute system where N is the number of
            events requiring an adjoint simulation.

        :rtype: None
        :return: This function is not expected to return anything
        """
        raise NotImplementedError('Must be implemented by subclass.')

    def run_single(self, classname, method, *args, **kwargs):
        """
        Runs a task a single time

        .. note::
            The expected behavior of the run_single() function is to submit ONE
            job to the compute system. This could be used for, submitting a job
            to smooth a model, which only needs to be done once.

        :rtype: None
        :return: This function is not expected to return anything
        """
        raise NotImplementedError('Must be implemented by subclass.')

    def taskid(self):
        """
        Provides a unique identifier for each running task. This is
        compute system specific.

        :rtype: int
        :return: this function is expected to return a unique numerical
            identifier.
        """
        raise NotImplementedError('Must be implemented by subclass.')

    def checkpoint(self, path, classname, method, args, kwargs):
        """
        Writes the SeisFlows3 working environment to disk so that new tasks can
        be executed in a separate/new/restarted working environment.

        :type path: str
        :param path: path the kwargs
        :type classname: str
        :param classname: name of the class to save
        :type method: str
        :param method: the specific function to be checkpointed
        :type kwargs: dict
        :param kwargs: dictionary to pass to object saving
        """
        self.logger.debug("checkpointing working environment to disk")

        argspath = os.path.join(path, "kwargs")
        argsfile = os.path.join(argspath, f"{classname}_{method}.p")
        unix.mkdir(argspath)
        saveobj(argsfile, kwargs)
        save()

