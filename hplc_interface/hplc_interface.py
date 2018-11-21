from __future__ import print_function, division
import time
import os
import yaml
from threading import Timer
import signal
import sys
import shutil
from datetime import datetime
import csv

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
    _SECONDS_PER_MINUTE = 60

    def __init__(self,*args,**kwargs):
        self.is_setup = False
        signal.signal(signal.SIGINT,self._signal_handler)
        if 'debug' in kwargs:
            self.debug = kwargs['debug']
        else:
            kwargs.update({'debug': DEBUG})
            self.debug = DEBUG
        self._base_path = os.path.expanduser('~/Desktop')
        self._data_base_path = os.path.join(self._base_path,'data')
        self._args = args
        self._kwargs = kwargs
        self._data_fieldnames = [
            'duration',
            'gradient_state',
            'concentration',
            'detector_status',
        ]

    def _signal_handler(self,sig,frame):
        self.stop()
        try:
            sys.exit(0)
        except SystemExit as e:
            pass

    def _debug_print(self, *args):
        if self.debug:
            print(*args)

    def _get_date_time_str(self,timestamp=None):
        if timestamp is None:
            d = datetime.fromtimestamp(time.time())
        elif timestamp == 0:
            date_time_str = 'NULL'
            return date_time_str
        else:
            d = datetime.fromtimestamp(timestamp)
        date_time_str = d.strftime('%Y-%m-%d-%H-%M-%S')
        return date_time_str

    def _get_time_from_date_time_str(self,date_time_str):
        if date_time_str != 'NULL':
            timestamp = time.mktime(datetime.strptime(date_time_str,'%Y-%m-%d-%H-%M-%S').timetuple())
        else:
            timestamp = 0
        return timestamp

    def _setup(self):
        t_start = time.time()
        self._load_config_file()
        self._setup_modular_clients()
        self._configure()
        self._has_been_injected = False
        self._injection_time = None
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
        print('detecting USB devices...')
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
            if self.detector_connected:
                self.ultraviolet_detector_interface.turn_lamp_on()
                print('turning on detector lamp')
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

        self._wavelengths = self._config['detector']['wavelengths']
        while True:
            wavelength_count_diff = len(self._wavelengths) - self._WAVELENGTH_COUNT
            if wavelength_count_diff > 0:
                self._wavelengths.pop()
            elif wavelength_count_diff < 0:
                self._wavelengths.append(wavelengths[-1])
            else:
                break
        self._data_fieldnames.extend(self._wavelengths)
        if self.detector_connected:
            print()
            self.ultraviolet_detector_interface.set_wavelengths(self._wavelengths)
            wavelengths_set = self.ultraviolet_detector_interface.get_wavelengths()
            if self._wavelengths == wavelengths_set:
                print(f'detector wavelengths set to {wavelengths_set}')
            else:
                raise RuntimeError(f'Detector wavelengths not set properly.')

    def start(self):
        if not self.is_setup:
            self._setup()
        self.is_running = True
        print()
        print('Setting up data files.')
        date_time_str = self._get_date_time_str()
        self._data_path = os.path.join(self._data_base_path,date_time_str)
        os.makedirs(self._data_path)
        config_filename = f'config-{date_time_str}.yaml'
        config_path = os.path.join(self._data_path,config_filename)
        print()
        print('copying config.yaml to:')
        print(config_path)
        shutil.copyfile(self._config_file_path,config_path)
        data_filename = f'data-{date_time_str}.csv'
        data_path = os.path.join(self._data_path,data_filename)
        print()
        print('creating:')
        print(data_path)
        print()
        self._data_file = open(data_path,'w')
        self._data_writer = csv.DictWriter(self._data_file,fieldnames=self._data_fieldnames)
        self._data_writer.writeheader()

        self._sample_timer = Timer(1.0/self._SAMPLE_FREQUENCY,self._sample)
        self._sample_timer.start()

    def _sample(self):
        if self.is_setup and self.is_running:
            gradient_info = self.hplc_controller.get_gradient_info()
            gradient_state = gradient_info['state']
            detector_status = 'NOT_CONNECTED'
            got_absorbances = False
            if self.detector_connected:
                detector_status = self.ultraviolet_detector_interface.get_status()
            if gradient_state == 'GRADIENT_NOT_STARTED':
                if detector_status == 'MEASUREMENT':
                    print('waiting for injection')
                elif detector_status == 'NOT_CONNECTED':
                    print('detector not connected, inject to test gradient')
                else:
                    print('do not inject yet, waiting for detector lamp')
            elif gradient_state == 'FINISHED':
                self.stop()
                return
            else:
                if not self._has_been_injected:
                    self._has_been_injected = True
                    self._injection_time = time.time()
                    print()
                    print('injected!')
                    if self.detector_connected:
                        self.ultraviolet_detector_interface.autozero()
                        print()
                        print('autozeroing detector')
                if self.detector_connected:
                    detector_status = self.ultraviolet_detector_interface.get_status()
                    if detector_status == 'MEASUREMENT':
                        absorbances = self.ultraviolet_detector_interface.get_absorbances()
                        got_absorbances = True
                    else:
                        print('waiting for detector to autozero')
                else:
                    absorbances = [0 for wavelength in self._wavelengths]
                    got_absorbances = True
                if got_absorbances:
                    data = {}
                    duration = (time.time() - self._injection_time)/self._SECONDS_PER_MINUTE
                    data['duration'] = f'{duration:.3f}'
                    data['gradient_state'] = gradient_state
                    data['concentration'] = gradient_info['concentration']
                    data['detector_status'] = detector_status
                    wavelength_absorbances = zip(self._wavelengths,absorbances)
                    for wavelength,absorbance in wavelength_absorbances:
                        data[wavelength] = '{:.2f}'.format(absorbance)
                    self._data_writer.writerow(data)
                    print(data)
            self._sample_timer = Timer(1.0/self._SAMPLE_FREQUENCY,self._sample)
            self._sample_timer.start()

    def stop(self):
        self.is_running = False
        if self.is_setup:
            self._sample_timer.cancel()
            self.hplc_controller.stop()
            self._data_file.close()
            if self.detector_connected:
                self.ultraviolet_detector_interface.turn_lamp_off()

def main(args=None):
    debug = False
    # if args is None:
    #     args = sys.argv[1:]
    hplc_interface = HplcInterface(debug=debug)
    hplc_interface.start()

# -----------------------------------------------------------------------------------------
if __name__ == '__main__':
    main()
