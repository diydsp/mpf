"""Contains the Config and CaseInsensitiveDict base classes."""

import errno
import hashlib
import logging
import os
import pickle
import tempfile
from typing import List, Tuple

from mpf.core.file_manager import FileManager
from mpf.core.utility_functions import Util
from mpf.core.config_validator import ConfigValidator


class ConfigProcessor(object):

    """Config processor which loads the config."""

    def __init__(self):
        """Initialise config processor."""
        self.log = logging.getLogger("ConfigProcessor")

    @staticmethod
    def get_cache_filename(filenames: List[str]) -> str:   # pragma: no cover
        """Return cache file name."""
        cache_dir = tempfile.gettempdir()
        filestring = ""
        for configfile in filenames:
            filestring += str(os.path.abspath(configfile))
        path_hash = hashlib.md5(bytes(filestring, 'UTF-8')).hexdigest()
        return os.path.join(cache_dir, path_hash + ".mpf_cache")

    def _load_config_from_cache(self, cache_file) -> dict:
        """Return config from cache."""
        self.log.info("Loading config from cache: %s", cache_file)
        with open(cache_file, 'rb') as f:
            try:
                data = pickle.load(f)
            # unfortunately pickle can raise all kinds of exceptions and we dont want to crash on corrupted cache
            # pylint: disable-msg=broad-except
            except Exception:   # pragma: no cover
                self.log.warning("Could not load cache file: %s", cache_file)
                return None, None

        if not isinstance(data, tuple) or len(data) != 2:
            return None, None
        return data

    def _get_mtime_or_negative(self, filename) -> int:
        """Return mtime or -1 if file could not be found."""
        try:
            return os.path.getmtime(filename)
        except OSError as exception:
            if exception.errno != errno.ENOENT:
                raise  # some unknown error?
            else:
                self.log.warning('Cache file not found: %s', filename)
                return -1

    def load_config_files_with_cache(self, filenames: List[str], config_type: str, load_from_cache=True,
                                     store_to_cache=True) -> dict:   # pragma: no cover
        """Load multiple configs with a combined cache."""
        config = dict()
        # Step 1: Check timestamps of the filelist vs cache
        cache_file = self.get_cache_filename(filenames)
        if load_from_cache:
            cache_time = self._get_mtime_or_negative(cache_file)
            if cache_time < 0:
                load_from_cache = False

        if load_from_cache:
            for configfile in filenames:
                if self._get_mtime_or_negative(configfile) > cache_time:
                    load_from_cache = False
                    self.log.warning('Config file in cache changed: %s', configfile)
                    break

        # Step 2: Get cache content
        if load_from_cache:
            config, loaded_files = self._load_config_from_cache(cache_file)
            if not config:
                load_from_cache = False
        else:
            loaded_files = None

        # Step 3: Check timestamps of included files vs cache
        if loaded_files:
            for configfile in loaded_files:
                if self._get_mtime_or_negative(configfile) > cache_time:
                    load_from_cache = False
                    self.log.warning('Config file in cache changed: %s', configfile)
                    break

        # Step 4: Return cache
        if load_from_cache:
            return config

        # Step 5: If we did not get it from cache load it from files
        if not ConfigValidator.config_spec:
            ConfigValidator.load_config_spec()

        config = dict()
        loaded_files = []
        for configfile in filenames:
            self.log.info('Loading config from file %s.', configfile)
            file_config, file_subfiles = self._load_config_file_and_return_loaded_files(configfile, config_type)
            loaded_files.extend(file_subfiles)
            config = Util.dict_merge(config, file_config)

        # Step 6: Store to cache
        if store_to_cache:
            with open(cache_file, 'wb') as f:
                pickle.dump((config, loaded_files), f, protocol=4)
                self.log.info('Config file cache created: %s', cache_file)

        return config

    def _load_config_file_and_return_loaded_files(
            self, filename, config_type: str,
            ignore_unknown_sections=False) -> Tuple[dict, List[str]]:   # pragma: no cover
        """Load a config file and return loaded files."""
        # config_type is str 'machine' or 'mode', which specifies whether this
        # file being loaded is a machine config or a mode config file
        config = FileManager.load(filename, True, True)
        subfiles = []

        if not ConfigValidator.config_spec:
            ConfigValidator.load_config_spec()

        if not config:
            return dict(), []

        self.log.info('Loading config: %s', filename)

        for k in config.keys():
            try:
                if config_type not in ConfigValidator.config_spec[k][
                        '__valid_in__']:
                    raise ValueError('Found a "{}:" section in config file {}, '
                                     'but that section is not valid in {} config '
                                     'files.'.format(k, filename, config_type))
            except KeyError:
                if not ignore_unknown_sections:
                    raise ValueError('Found a "{}:" section in config file {}, '
                                     'but that section is not valid in {} config '
                                     'files.'.format(k, filename, config_type))

        try:
            if 'config' in config:
                path = os.path.split(filename)[0]

                for file in Util.string_to_list(config['config']):
                    full_file = os.path.join(path, file)
                    subfiles.append(full_file)
                    subconfig, subsubfiles = self._load_config_file_and_return_loaded_files(full_file, config_type)
                    subfiles.extend(subsubfiles)
                    config = Util.dict_merge(config, subconfig)
            return config, subfiles
        except TypeError:
            return dict(), []

    @staticmethod
    def load_config_file(filename, config_type: str,
                         ignore_unknown_sections=False) -> dict:   # pragma: no cover
        """Load a config file."""
        # config_type is str 'machine' or 'mode', which specifies whether this
        # file being loaded is a machine config or a mode config file
        config = FileManager.load(filename, True, True)

        if not ConfigValidator.config_spec:
            ConfigValidator.load_config_spec()

        if not config:
            return dict()

        for k in config.keys():
            try:
                if config_type not in ConfigValidator.config_spec[k][
                        '__valid_in__']:
                    raise ValueError('Found a "{}:" section in config file {}, '
                                     'but that section is not valid in {} config '
                                     'files.'.format(k, filename, config_type))
            except KeyError:
                if not ignore_unknown_sections:
                    raise ValueError('Found a "{}:" section in config file {}, '
                                     'but that section is not valid in {} config '
                                     'files.'.format(k, filename, config_type))

        try:
            if 'config' in config:
                path = os.path.split(filename)[0]

                for file in Util.string_to_list(config['config']):
                    full_file = os.path.join(path, file)
                    config = Util.dict_merge(config,
                                             ConfigProcessor.load_config_file(
                                                 full_file, config_type))
            return config
        except TypeError:
            return dict()
