from datetime import datetime
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from flask import Flask, jsonify, Response
import sys,os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname( __file__ ), '../', 'resources')))
import config as cfg

restarted=True
BaerNas_Sync = Gauge('BaerNasSync_transfered', 'BaerNasSync_transfered', ['type','action','name'])

app = Flask(__name__)
@app.route('/metrics')
def metrics():
    #doit(REQUEST_COUNTER)
    try:
        if restarted or datetime.today().strftime('%H:%M') == "06:00":
            get_metrics()
        data= generate_latest()
        return Response(data, mimetype=CONTENT_TYPE_LATEST)
    except Exception as ex:
        return Response(f"Error generating metrics: {ex}", status=500, mimetype='text/plain')




def get_metrics():



    #print(find_from_bottom_simple("/mnt/BaerNas/Raspberry/nasbackup/RCLONE_CloudBackup.log.dokumente.log", "2025/10/19"))
    current_date=datetime.today().strftime('%Y/%m/%d')

    #current_date="2025/11/01"
    deleted=""

    for logfile in App_Config.config["loglist"]["scrape_list"]:
        transfered=0
        deleted=0
        deleted_dirs=0
        deleted_files=0
        global restarted
        
        restarted=False
        with open(logfile["path"]) as f:
            l=f.readlines()
            for lineno in range(len(l),-1,-1):
                #print(l[lineno-1])
                if current_date in l[lineno-1] and "Transferred" in l[lineno+1]:
                    if "Deleted" in l[lineno+3]:
                        #print(l[lineno])
                        deleted=l[lineno + 3 ]
                        if "Transferred" in l[lineno+4]:
                            transfered=l[lineno + 4]
                    elif "Transferred" in l[lineno +3]:
                        #print(l[lineno])
                        transfered=l[lineno + 3]
                    break
                
                

        try:
            if isinstance(deleted, str):
                deleted_files=int(deleted.split("(files)")[0].replace("Deleted:","").strip())
                deleted_dirs=int(deleted.split("(dirs)")[0].split(",")[1].strip())
        except:
            deleted_dirs=-1
            deleted_files=-1
            pass
        try:
            if isinstance(transfered, str):
                transfered=int(transfered.split("/")[1].split(",")[0].strip())
        except:
            transfered=-1
            pass

        BaerNas_Sync.labels(type="files", action="transfered", name=logfile["name"]).set(transfered)
        BaerNas_Sync.labels(type="folder", action="deleted", name=logfile["name"]).set(deleted_dirs)
        BaerNas_Sync.labels(type="files", action="deleted", name=logfile["name"]).set(deleted_files)
        #print(f"{logfile}\nDeleted: {deleted_files} files, {deleted_dirs} dirs\nSaved: {transfered} files")            
    pass        


if __name__ == '__main__':
    restarted=True

    App_Config=cfg.app_config(str(__file__).replace(".py",".yml"))
    app.run(host='0.0.0.0', port=App_Config.get("config.ExporterPort"))    
    #app.run(host='0.0.0.0', port=5000)
