import yaml
import logging
from logging.handlers import RotatingFileHandler
import sys, os


class app_config():
    def __init__(self, configfile):
        self.configfile = configfile
        self.config = self.__opencfg__()
        try:
            self.loglevel=None
            self.loglevel=self.get("config.LogLevel")
            self.logfilename=configfile.replace("yml", "log")
            self.logfilename=self.get("config.LogFileName")
            self.log=self.__create_rotating_log__(self.logfilename)
        except:
            pass
        

    def __opencfg__(self):
        try:
            with open(self.configfile, 'r') as file:
                self.config = yaml.safe_load(file)
        except Exception as ex:
            raise Exception("Error reading configfile: {}".format(str(ex)))

    def get(self, path):
        try:
            self.__opencfg__()
            value = self.__drill_down__(self.config, path.split("."))
            return value
        except Exception as ex:
            raise Exception("Element not found in {}: {}".format(self.configfile,str(ex)))

    def __drill_down__(self,yml_dict, path):
        if len(path) == 1: 
            # if path has a single element, return that key of the dict
            try:
                return yml_dict[path[0]]
            except Exception as ex:
                raise Exception(str(ex))

        else:
        # Take the key given by the first element of path. Then drill down into it
            try:
                return self.__drill_down__(yml_dict[path[0]], path[1:])         
            except Exception as ex:
                raise Exception(str(ex))
            

    def __create_rotating_log__(self, path):
        logger = logging.getLogger("Rotating Log")
        try:
            setattr(logger, "level", getattr(logging,self.loglevel))
            #logger.setLevel(self.logging.DEBUG)
        except:
            logger.setLevel(logging.DEBUG)

        handler = RotatingFileHandler(path, maxBytes=10000000, backupCount=5)
        formatter = logging.Formatter(
            fmt='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        return logger
