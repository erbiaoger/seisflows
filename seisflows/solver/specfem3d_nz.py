
import subprocess
from glob import glob
from os.path import join

import sys
import numpy as np

import seisflows.plugins.solver.specfem3d as solvertools
from seisflows.tools.seismic import getpar, setpar

from seisflows.tools import unix
from seisflows.tools.seismic import call_solver
from seisflows.tools.tools import exists
from seisflows.config import ParameterError, custom_import

PAR = sys.modules['seisflows_parameters']
PATH = sys.modules['seisflows_paths']

system = sys.modules['seisflows_system']
preprocess = sys.modules['seisflows_preprocess']


class specfem3d_nz(custom_import('solver', 'base')):
    """ Python interface for SPECFEM3D

      See base class for method descriptions
    """
    def check(self):
        """ Checks parameters and paths
        """
        super(specfem3d_nz, self).check()

        # check time stepping parameters
        if 'NT' not in PAR:
            raise Exception

        if 'DT' not in PAR:
            raise Exception

        if 'F0' not in PAR:
            raise Exception

        # check data format
        if 'FORMAT' not in PAR:
            raise Exception()

        # make sure data format is accetapble
        if PAR.FORMAT not in ['su', 'sem']:
            raise Exception()

    def generate_data(self, **model_kwargs):
        """ Generates data in the synthetic-synthetic comparison case.
        Not for use in the real-data problem.
        """
        print 'generate data'
        self.generate_mesh(**model_kwargs)

        unix.cd(self.cwd)
        setpar('SIMULATION_TYPE', '1')
        setpar('SAVE_FORWARD', '.true.')
        call_solver(system.mpiexec(), 'bin/xspecfem3D')

        if PAR.FORMAT in ['SU', 'su']:
            src = glob('OUTPUT_FILES/*_d?_SU')
            dst = 'traces/obs'
            unix.mv(src, dst)

        if PAR.SAVETRACES:
            self.export_traces(PATH.OUTPUT+'/'+'traces/obs')

    def generate_mesh(self, model_path=None, model_name=None, model_type='gll'):
        """ Performs meshing and database generation
        """
        print 'generate mesh'
        assert(model_name)
        assert(model_type)

        self.initialize_solver_directories()
        unix.cd(self.cwd)

        if model_type in ['gll']:
            par = getpar('MODEL').strip()
            if par != 'gll':
                if self.taskid == 0:
                    print 'WARNING: Unexpected Par_file setting:'
                    print 'MODEL =', par
            
            assert(exists(model_path))
            self.check_mesh_properties(model_path)

            src = glob(model_path +'/'+ '*')
            dst = self.model_databases
            unix.cp(src, dst)

            # bchow 
            # call_solver(system.mpiexec(), 'bin/xmeshfem3D')
            call_solver(system.mpiexec(), 'bin/xgenerate_databases')

            if self.taskid == 0:
                self.export_model(PATH.OUTPUT +'/'+ model_name)

        else:
            raise NotImplementedError

    def eval_func(self, path='', iter='', *args, **kwargs):
        """
        evaluate the misfit functional using the external package Pyatoa.
        Pyatoa is written in Python3 so it needs to be called with subprocess
        :param args:
        :param kwargs:
        :return:
        """
        # generate the synthetics
        unix.cd(self.cwd)
        self.import_model()
        self.forward()

        # calling bash script to call Pyatoa. Parameters are passed through
        # the bash script to Pyatoa via positional command line arguments
        subprocess.call(system.mpiexec(),
                        join(PATH.WORKDIR, 'run_process_seisflows.sh '),
                        self.source_name,                    # event_id
                        str(int(iter) - 1),                  # model_number
                        join(self.cwd, 'traces', 'syn'),     # synthetic_dir
                        PATH.WORKDIR,                        # working_dir
                        join(PATH.WORKDIR, 'pyatoa.output')  # output_dir
                        )


    # low-level solver interface
    def forward(self, path='traces/syn'):
        """ Calls SPECFEM3D forward solver and then moves files into path
        """
        setpar('SIMULATION_TYPE', '1')
        setpar('SAVE_FORWARD', '.true.')
        call_solver(system.mpiexec(), 'bin/xgenerate_databases')
        call_solver(system.mpiexec(), 'bin/xspecfem3D')

        # seismic unix output format
        if PAR.FORMAT in ['SU', 'su']:
            src = glob('OUTPUT_FILES/*_d?_SU')
            dst = path
            unix.mv(src, dst)
        # sem output format
        elif PAR.FORMAT == "sem":
            src = glob('OUTPUT_FILES/*_sem?')
            dst = path
            unix.mv(src, dst)

    def adjoint(self):
        """ Calls SPECFEM3D adjoint solver
        """
        setpar('SIMULATION_TYPE', '3')
        setpar('SAVE_FORWARD', '.false.')
        unix.rm('SEM')
        unix.ln('traces/adj', 'SEM')
        call_solver(system.mpiexec(), 'bin/xspecfem3D')

    # input file writers
    def check_solver_parameter_files(self):
        """ Checks solver parameters
        """
        nt = getpar('NSTEP', cast=int)
        dt = getpar('DT', cast=float)

        if nt != PAR.NT:
            if self.taskid == 0: print "WARNING: nt != PAR.NT"
            setpar('NSTEP', PAR.NT)

        if dt != PAR.DT:
            if self.taskid == 0: print "WARNING: dt != PAR.DT"
            setpar('DT', PAR.DT)

        if self.mesh_properties.nproc != PAR.NPROC:
            if self.taskid == 0:
                print 'Warning: mesh_properties.nproc != PAR.NPROC'

        if 'MULTIPLES' in PAR:
            raise NotImplementedError

    def initialize_adjoint_traces(self):
        super(specfem3d_nz, self).initialize_adjoint_traces()

        # workaround for SPECFEM2D's use of different name conventions for
        # regular traces and 'adjoint' traces
        if PAR.FORMAT in ['SU', 'su']:
            files = glob(self.cwd + '/' + 'traces/adj/*SU')
            unix.rename('_SU', '_SU.adj', files)

        # workaround for SPECFEM3D's requirement that all components exist,
        # even ones not in use
        unix.cd(self.cwd + '/' + 'traces/adj')
        for iproc in range(PAR.NPROC):
            for channel in ['x', 'y', 'z']:
                src = '%d_d%s_SU.adj' % (iproc, PAR.CHANNELS[0])
                dst = '%d_d%s_SU.adj' % (iproc, channel)
                if not exists(dst):
                    unix.cp(src, dst)

    def rename_data(self):
        """ Works around conflicting data filename conventions
        """
        if PAR.FORMAT in ['SU', 'su']:
            files = glob(self.cwd + '/' + 'traces/adj/*SU')
            unix.rename('_SU', '_SU.adj', files)

    def write_parameters(self):
        unix.cd(self.cwd)
        solvertools.write_parameters(vars(PAR))

    def write_receivers(self):
        unix.cd(self.cwd)
        key = 'use_existing_STATIONS'
        val = '.true.'
        setpar(key, val)
        _, h = preprocess.load('traces/obs')
        solvertools.write_receivers(h.nr, h.rx, h.rz)

    def write_sources(self):
        unix.cd(self.cwd)
        _, h = preprocess.load(dir='traces/obs')
        solvertools.write_sources(vars(PAR), h)

    # miscellaneous
    @property
    def data_wildcard(self):
        channels = PAR.CHANNELS
        return '*_d[%s]_SU' % channels.lower()

    @property
    def data_filenames(self):
        unix.cd(self.cwd+'/'+'traces/obs')

        if PAR.FORMAT in ['SU', 'su']:
            if not PAR.CHANNELS:
                return sorted(glob('*_d?_SU'))
            filenames = []
            for channel in PAR.CHANNELS:
                filenames += sorted(glob('*_d'+channel+'_SU'))
            return filenames

        else:
            raise NotImplementedError

    @property
    def kernel_databases(self):
        return join(self.cwd, 'OUTPUT_FILES/DATABASES_MPI')

    @property
    def model_databases(self):
        return join(self.cwd, 'OUTPUT_FILES/DATABASES_MPI')

    @property
    def source_prefix(self):
        return 'CMTSOLUTION'
