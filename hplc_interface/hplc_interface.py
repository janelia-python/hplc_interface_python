from __future__ import print_function, division
import time
import os
import yaml
from threading import Timer
import signal
import sys

# from datetime import datetime
# import csv

from modular_client import ModularClients

try:
    from pkg_resources import get_distribution, DistributionNotFound
    _dist = get_distribution('hplc_interface')
    # Normalize case for Windows systems
    dist_loc = os.path.normcase(_dist.location)
    here = os.path.normcase(__file__)
    if not here.startswith(os.path.join(dist_loc, 'hplc_interface')):
        # not installed, but there is another version that *is*
        raise DistributionNotFound
except (ImportError,DistributionNotFound):
    __version__ = None
else:
    __version__ = _dist.version


DEBUG = False

class HplcInterface():
    '''
    HplcInterface.

    Example Usage:

    dev = HplcInterface() # Might automatically find devices if available
    '''

    _CONFIG_FILENAME = 'config.yaml'
    _WAVELENGTH_COUNT = 4
    _DETECTOR = 'ultraviolet_detector_interface'
    _SAMPLE_FREQUENCY = 1
    _TIMEOUT = 4.0

    def __init__(self,*args,**kwargs):
        self.is_setup = False
        signal.signal(signal.SIGINT,self._signal_handler)
        if 'debug' in kwargs:
            self.debug = kwargs['debug']
        else:
            kwargs.update({'debug': DEBUG})
            self.debug = DEBUG
        self._base_path = os.path.expanduser('~/Desktop')
        self._args = args
        self._kwargs = kwargs

    def _signal_handler(self,sig,frame):
        self.stop()
        try:
            sys.exit(0)
        except SystemExit as e:
            pass

    def _debug_print(self, *args):
        if self.debug:
            print(*args)

    def _setup(self):
        t_start = time.time()
        self._load_config_file()
        self._setup_modular_clients()
        self._configure()
        t_end = time.time()
        self.is_setup = True
        self._debug_print('Setup time =', (t_end - t_start))

    def _load_config_file(self):
        print()
        print('loading config.yaml...')
        self._config_file_path = os.path.join(self._base_path,self._CONFIG_FILENAME)
        with open(self._config_file_path,'r') as config_stream:
            self._config = yaml.load(config_stream)
        print('config.yaml loaded successfully')

    def _setup_modular_clients(self):
        print()
        print('Detecting USB devices...')
        self._modular_clients = ModularClients(*self._args,**self._kwargs,timeout=self._TIMEOUT)
        hc_name = 'hplc_controller'
        hc_form_factor = '3x2'
        hc_serial_number = 0
        if (hc_name not in self._modular_clients):
            raise RuntimeError(hc_name + ' is not connected!')
        self.hplc_controller = self._modular_clients[hc_name][hc_form_factor][hc_serial_number]
        print()
        print(f'{hc_name} is connected')

        udi_name = 'ultraviolet_detector_interface'
        udi_form_factor = '3x2'
        udi_serial_number = 0
        if (udi_name not in self._modular_clients):
            raise RuntimeError(udi_name + ' is not connected!')
        self.ultraviolet_detector_interface = self._modular_clients[udi_name][udi_form_factor][udi_serial_number]
        print()
        print(f'{udi_name} is connected')
        try:
            detector_info = self.ultraviolet_detector_interface.get_detector_info()
            print(f'detector_info: {detector_info}')
            self.detector_connected = True
        except IOError:
            print(f'ECOM Toydad UV detector is not connected to the {udi_name}!')
            self.detector_connected = False

    def _configure(self):
        print()
        gradient = self._config['gradient']
        for gradient_property in gradient:
            value_to_set = gradient[gradient_property]
            value_set = getattr(self.hplc_controller,gradient_property)()
            if value_to_set == value_set:
                print(f'{gradient_property} set to {value_set}')
            else:
                raise RuntimeError(f'Gradient property {gradient_property} not set properly.')

        wavelengths = self._config['detector']['wavelengths']
        while True:
            wavelength_count_diff = len(wavelengths) - self._WAVELENGTH_COUNT
            if wavelength_count_diff > 0:
                wavelengths.pop()
            elif wavelength_count_diff < 0:
                wavelengths.append(wavelengths[-1])
            else:
                break
        if self.detector_connected:
            print()
            self.ultraviolet_detector_interface.set_wavelengths(wavelengths)
            wavelengths_set = self.ultraviolet_detector_interface.get_wavelengths()
            if wavelengths == wavelengths_set:
                print(f'detector wavelengths set to {wavelengths_set}')
            else:
                raise RuntimeError(f'Detector wavelengths not set properly.')

    def start(self):
        if not self.is_setup:
            self._setup()
        self.is_running = True
        self._sample_timer = Timer(1.0/self._SAMPLE_FREQUENCY,self._sample)
        self._sample_timer.start()

    def _sample(self):
        if self.is_setup and self.is_running:
            gradient_info = self.hplc_controller.get_gradient_info()
            print(gradient_info)
            self._sample_timer = Timer(1.0/self._SAMPLE_FREQUENCY,self._sample)
            self._sample_timer.start()

    def stop(self):
        self.is_running = False
        if self.is_setup:
            self._sample_timer.cancel()
            self.hplc_controller.stop()

def main(args=None):
    debug = False
    # if args is None:
    #     args = sys.argv[1:]
    hplc_interface = HplcInterface(debug=debug)
    hplc_interface.start()

# -----------------------------------------------------------------------------------------
if __name__ == '__main__':
    main()
