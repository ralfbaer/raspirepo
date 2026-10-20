import sys,os
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from time import sleep
import datetime
sys.path.append(os.path.abspath(os.path.join(os.path.dirname( __file__ ), '../', 'resources')))

from config import app_config

def doPing(hosts):
    from tcping import Ping
    json_body = []
    measurement = App_Config.get("config.InfluxDB_Measurement")
    for host in hosts:
        port=host.split(":")[1]
        host=host.split(":")[0]
        body={}
        ping = Ping(host, int(port), App_Config.get("config.pingtimeout"))
        try:
            ping.ping(1)
            if ping._failed == 1:
                raise Exception(ping.result.raw)
            body.update({"measurement": measurement, "tags":{"host":host}, "fields": {"value": ping._conn_times[0]}})
            json_body.append(body)
            pass
        except Exception as ex:
            body.update({"measurement": measurement, "tags":{"host":host}, "fields": {"value": -100.0}})
            json_body.append(body)
            print(str(ex))
    pass
    WriteToDB(json_body)

def WriteToDB(data):
                InfluxBucketName = App_Config.get("config.InfluxDB_BUCKET")
                InfluxOrganisationName = App_Config.get("config.InfluxDB_ORG")
                InfluxURL = App_Config.get("config.InfluxDB_URL")
                InfluxToken = App_Config.get("config.InfluxDB_APIKey")

                

                InfluxDB_client = influxdb_client.InfluxDBClient(url=InfluxURL, token=InfluxToken, org=InfluxOrganisationName)
                InfluxDB_write_api = InfluxDB_client.write_api(write_options=SYNCHRONOUS)
                InfluxDB_write_api.write(bucket=InfluxBucketName , record=data)

if __name__ == '__main__':
    App_Config=app_config(str(__file__).replace(".py",".yml"))
    while True:
        try:
            print(str(datetime.datetime.now())+": run ping...")
            doPing(App_Config.get("config.scrapelist"))
            print(str(datetime.datetime.now())+": ping finished")
            sleep(App_Config.get("config.scrapetime"))
        except Exception as ex:
            print(str(ex))
    pass
    #WriteToDB()