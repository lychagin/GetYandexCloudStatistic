import json
import os
import requests
import time
import sys
import jwt
import logging
import db

from periods import VmDict
from datetime import datetime, timezone, timedelta
from requests.exceptions import HTTPError

# Ссылка на расценки: https://yandex.cloud/ru/docs/compute/pricing?utm_referrer=about%3Ablank
SSD_GB_PRICE_MONTH = 11.91  # Быстрый диск (SSD)
SSD_NR_GB_PRICE_MONTH = 8.80  # Нереплицируемый диск (SSD)
HDD_GB_PRICE_MONTH = 2.92  # Cтандартный диск (HDD)
IMAGE_PRICE_MONTH = 3.12
SNAPSHOT_PRICE_MONTH = 3.12
WORK_HOURS = 24
HOURS_MONTH = 720
HOURS_DAY = 24
DISCOUNT = 0.75  # discount in 25%
SECONDS_IN_DAY = 24 * 60 * 60

FOLDER_ID = ''
IAM_KEY = ''
IAM_KEY_EXPIRES = ''

YC_INSTANCE_LIST = "https://compute.api.cloud.yandex.net/compute/v1/instances"
YC_DISK_GET = "https://compute.api.cloud.yandex.net/compute/v1/disks/"
YC_IMAGES_LIST = "https://compute.api.cloud.yandex.net/compute/v1/images"
YC_SNAPSHOT_LIST = "https://compute.api.cloud.yandex.net/compute/v1/snapshots"
YC_IAM_TOKEN = 'https://iam.api.cloud.yandex.net/iam/v1/tokens'
YC_INSTANCE_OPERATIONS_LIST = "https://compute.api.cloud.yandex.net/compute/v1/instances/{instanceId}/operations"

# https://yandex.cloud/ru/docs/compute/concepts/vm-platforms
PLATFORMS = {
    "standard-v1":
        {"name": "Intel Broadwell",
         "cpu": "Intel® Xeon® Processor E5-2660 v4",
         5: 0.31,  # CPU 5%
         20: 0.88,  # CPU 20%
         100: 1.12,  # CPU 100%
         "ram": 0.39
         },
    "standard-v2":
        {"name": "Intel Cascade Lake",
         "cpu": "Intel® Xeon® Gold 6230",
         5: 0.16,  # CPU 5%
         20: 0.49,  # CPU 20%
         50: 0.72,  # CPU 50%
         100: 1.19,  # CPU 100%
         "ram": 0.31
         },
    "standard-v3":
        {"name": "Intel Ice Lake",
         "cpu": "Intel® Xeon® Gold 6338",
         20: 0.44,  # CPU 20%
         50: 0.64,  # CPU 50%
         100: 1.05,  # CPU 100%
         "ram": 0.28
         }
}


def init_logging():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s: %(message)s', datefmt='%m/%d/%Y %H:%M:%S',
                        stream=sys.stdout)


def get_jwt_token(filename):
    logging.info("get_jwt_token")
    file = open(filename)
    data = json.load(file)
    file.close()

    key_id = data.get("id", "")
    service_account_id = data.get("service_account_id", "")
    private_key = data.get("private_key", "")

    now = int(time.time())
    payload = {
        'aud': 'https://iam.api.cloud.yandex.net/iam/v1/tokens',
        'iss': service_account_id,
        'iat': now,
        'exp': now + 360}

    encoded_token = jwt.encode(
        payload,
        private_key,
        algorithm='PS256',
        headers={'kid': key_id})

    return encoded_token


def get_iam_token(token):
    logging.info("get_iam_token")
    global IAM_KEY, IAM_KEY_EXPIRES
    response = {}
    result = True
    yc_headers = {"Content-Type": "application/json"}
    data_token = {"jwt": token}
    try:
        response = requests.post(YC_IAM_TOKEN, headers=yc_headers, json=data_token)
        response.raise_for_status()
    except HTTPError as e:
        logging.error(f"Error code: {response.status_code}")
        logging.error(f"Error description: {response.reason}")
        result = False

    if result:
        data = response.json()
        IAM_KEY = data.get("iamToken", "")
        # print("DEBUG: IAM_KEY: " + IAM_KEY)
        IAM_KEY_EXPIRES = data.get("expiresAt", "")


def yc_get_req(url, yc_params):
    response = {}
    result = True
    yc_headers = {"Accept": "application/json",
                  "Authorization": "Bearer " + IAM_KEY}
    try:
        response = requests.get(url, headers=yc_headers, params=yc_params)
        response.raise_for_status()
    except HTTPError as e:
        logging.error(f"Error in url: {url}")
        logging.error(f"Error code: {response.status_code}")
        logging.error(f"Error description: {response.reason}")
        result = False
        return result, ""

    # print("Success")
    # print("Result:")
    # print(json.dumps(response.json(), indent=2))
    return result, response.json()


def yc_get_disk_list(vm_cloud):
    logging.info(yc_get_disk_list.__name__)

    vm_disks = dict()
    for vmId, vm_info in vm_cloud.items():
        disk_id = vm_info.get("disk_id", 0)
        vm_disks[disk_id] = vmId

    orphaned_disks = dict()
    yc_params = {"folderId": FOLDER_ID,
                 "pageSize": 1000}
    data = yc_get_req(YC_DISK_GET, yc_params)
    if data[0]:
        disks = data[1]["disks"]
        for disk in disks:
            id = disk.get("id", 0)
            type = disk.get("typeId", "unknown")
            size_b = disk.get("size", 0)
            name = disk.get("name")
            logging.debug(f"Disk id: {id}, type: {type}, size_b = {size_b}")
            if id in vm_disks:
                vmId = vm_disks[id]
                vm_info = vm_cloud[vmId]
                vm_info["disk_type"] = type
                vm_info["disk_size_b"] = int(size_b)
                vm_info["disk_size_gb"] = int(size_b) / (1024 * 1024 * 1024)
            else:
                orphaned_disks[id] = name

    return orphaned_disks


def yc_get_snapshots():
    logging.info("yc_get_snapshots")
    snap_list = []
    yc_params = {"folderId": FOLDER_ID,
                 "pageSize": 1000}
    data = yc_get_req(YC_SNAPSHOT_LIST, yc_params)
    if data[0]:
        snp_list = data[1].get("snapshots")
        if snp_list:
            for snapshot in snp_list:
                # print("DEBUG: snapshot: {}".format(str(image)))
                snapshot_info = dict()
                snapshot_info["id"] = snapshot.get("id", 0)
                snapshot_info["createdAt"] = datetime.strptime(snapshot.get("createdAt", "01.01.1900").split('T')[0],
                                                               "%Y-%m-%d").date()
                snapshot_info["name"] = snapshot.get("name", "noname")
                snapshot_info["description"] = snapshot.get("description", "no description")
                snapshot_info["storage_size_b"] = snapshot.get("storageSize", 0)
                snapshot_info["storage_size_gb"] = int(snapshot_info["storage_size_b"]) / (1024 * 1024 * 1024)
                snapshot_info["status"] = snapshot.get("status", "no status")
                snapshot_info["sourceDiskId"] = snapshot.get("sourceDiskId", "0")
                # Calculate price for snapshots
                snapshot_info["price_snapshot_month"] = SNAPSHOT_PRICE_MONTH * snapshot_info["storage_size_gb"]
                snapshot_info["price_snapshot_day"] = (snapshot_info["price_snapshot_month"] / HOURS_MONTH) * 24
                snap_list.append(snapshot_info)
    return snap_list


def yc_get_images():
    logging.info("yc_get_images")
    img_list = []
    yc_params = {"folderId": FOLDER_ID,
                 "pageSize": 1000}
    data = yc_get_req(YC_IMAGES_LIST, yc_params)
    if data[0]:
        images_list = data[1].get("images")
        for image in images_list:
            # print("DEBUG: image: {}".format(str(image)))
            image_info = dict()
            image_info["id"] = image["id"]
            image_info["name"] = image["name"]
            name = image_info["name"]
            image_info["createdAt"] = datetime.strptime(image["createdAt"].split('T')[0], "%Y-%m-%d").date()
            image_info["description"] = image.get("description", "")
            image_info["family"] = image.get("family", "")
            family = image_info["family"]
            image_info["storage_size_b"] = image.get("storageSize", 0)
            image_info["storage_size_gb"] = int(image_info["storage_size_b"]) / (1024 * 1024 * 1024)
            image_info["status"] = image.get("status", "no status")
            labels = image.get("labels", "")
            soft_name = ""
            if labels:
                soft_name = labels.get("software-name", "")
            image_info["soft_name"] = soft_name
            image_info["price_image_month"] = IMAGE_PRICE_MONTH * image_info["storage_size_gb"]
            image_info["price_image_day"] = (image_info["price_image_month"] / HOURS_MONTH) * 24

            img_list.append(image_info)
    return img_list


def yc_get_vm_list():
    logging.info("yc_get_vm_list")
    vm_dict = dict()
    nextPage = True

    yc_params = {"folderId": FOLDER_ID,
                 "pageSize": 100}

    while nextPage:
        data = yc_get_req(YC_INSTANCE_LIST, yc_params)
        if data[0]:
            if "nextPageToken" in data[1]:
                yc_params["pageToken"] = data[1].get("nextPageToken")
            else:
                nextPage = False
                if "pageToken" in yc_params:
                    del yc_params["pageToken"]
            instances_list = data[1].get("instances")
            for instance in instances_list:
                # print("DEBUG: instance: " + str(instance))
                vm_id = instance.get("id")
                vm_info = dict()
                vm_info["id"] = vm_id
                vm_info["mem_b"] = int(instance.get("resources", {}).get("memory", 0))
                vm_info["mem_gb"] = vm_info.get("mem_b", 0) / (1024 * 1024 * 1024)
                vm_info["cores"] = int(instance.get("resources", {}).get("cores", 0))
                vm_info["core_fraction"] = int(instance.get("resources", {}).get("coreFraction", 0))
                vm_info["disk_id"] = instance.get("bootDisk", {}).get("diskId", 0)
                vm_info["device_name"] = instance.get("bootDisk", {}).get("deviceName", "-")
                networkInterfaces = instance.get("networkInterfaces", {})
                if networkInterfaces:
                    vm_info["ip"] = networkInterfaces[0].get("primaryV4Address", {}).get("address", "-")
                else:
                    vm_info["ip"] = "-"

                vm_info["name"] = instance.get("name", "-")
                vm_info["fqdn"] = instance.get("fqdn", "-")
                vm_info["platform_id"] = instance.get("platformId", "0")
                vm_info["status"] = instance.get("status", "-")
                vm_info["description"] = instance.get("description", "")
                try:
                    date = datetime.strptime(instance.get("createdAt", "").split('T')[0], "%Y-%m-%d").date()
                except ValueError:
                    date = "1900/01/01"
                vm_info["createdAt"] = date

                vm_info["labels"] = instance.get("labels", "")
                labels = vm_info.get("labels", {})
                team = ""
                creator = ""
                autoshutdown = ""
                ttl = ""
                if labels:
                    team = labels.get("team", "")
                    creator = labels.get("creator", "")
                    autoshutdown = labels.get("autoshutdown", "none")
                    ttl = labels.get("ttl", "none")
                vm_info["team"] = team
                vm_info["creator"] = creator
                vm_info["autoshutdown"] = autoshutdown
                vm_info["ttl"] = ttl
                vm_dict[vm_id] = vm_info

    return vm_dict


def yc_get_stop_duration(vmId):
    """
    Определяем сколько уже времени виртуалка находиться в выключенном состоянии.
    Это нужно для того чтобы чистить машины которые давно уже выключены и больше не включались.

    Берем список всех операций которые выполнялись над машиной. Ищем самую последюю StopInstanceRequest операцию
    Дальше вычисляем сколько времени прошло с момента остановки.

    Полный список всех операций описан здесь: https://github.com/yandex-cloud/cloudapi/blob/master/yandex/cloud/compute/v1/instance_service.proto

    :param vmId: ID виртуалки
    :return: Если виртуалка останавливалась, то возвращаем время сколько вирутуалка находиться в выключенном состоянии.
             Список [дни, часы, минуты]
             Если не останавливалась, то пустой список
    """
    logging.debug(yc_get_stop_duration.__name__)

    stop_duration = []
    data = yc_get_req(YC_INSTANCE_OPERATIONS_LIST.format(instanceId=vmId), "")
    """
    По умолчанию порядок список операций над ВМ отсортирован по убыванию, но в документации нет гарантии что
    это всегда будет так.
    https://yandex.cloud/ru/docs/compute/api-ref/Instance/listOperations
    https://yandex.cloud/ru/docs/api-design-guide/concepts/operation#operation-listing
    https://yandex.cloud/ru/docs/api-design-guide/concepts/operation#monitoring
    Поэтому мы должны найти последнюю Stop операцию
    """
    if data[0]:
        operations_list = data[1].get("operations")
        if operations_list:
            now = datetime.now(timezone.utc)
            stopOperationFound = False
            stop_list = []
            for operation in operations_list:
                op_name = operation["metadata"]["@type"]
                stop_flag = op_name.find("StopInstanceMetadata")
                if stop_flag != -1:
                    stopOperationFound = True
                    createdat = operation["createdAt"]
                    op_date = datetime.fromisoformat(createdat)
                    difference = now - op_date
                    duration_in_s = difference.days * SECONDS_IN_DAY + difference.seconds
                    stop_list.append(duration_in_s)
            if stopOperationFound:
                stop_list.sort()
                stop_date = stop_list[0]
                days = divmod(stop_date, 86400)
                hours = divmod(days[1], 3600)
                minutes = divmod(hours[1], 60)
                stop_duration.append(days[0])
                stop_duration.append(hours[0])
                stop_duration.append(minutes[0])
            else:
                stop_duration.append(0)
                stop_duration.append(0)
                stop_duration.append(0)
    return stop_duration


def yc_get_vm_list_stopped_period(vm_list):
    logging.info(yc_get_vm_list_stopped_period.__name__)

    for id, vm in vm_list.items():
        status = vm["status"]
        vm["stopped_days"] = 0
        if status == "STOPPED":
            stopped_time = yc_get_stop_duration(id)
            if stopped_time:
                # logging.info("DEBUG:    Days stoppped: " + str(stopped_time[0]))
                vm["stopped_days"] = stopped_time[0]


def calc_prices_vm(cloud_vms):
    logging.info(calc_prices_vm.__name__)

    for vm in cloud_vms.values():
        vmId = vm.get("id")
        vmName = vm.get("name")
        logging.debug(f"Calculate price for vmId={vmId}, name={vmName}")
        uptime_daily = vm.get("uptime_daily", 0)
        uptime_daily_hours = int(uptime_daily / 3600)
        platform = PLATFORMS.get(vm.get("platform_id"))
        ram = vm.get("mem_gb", 0)
        ram_price = ram * platform.get("ram") * uptime_daily_hours
        vm["price_ram_day"] = ram_price
        cores = vm.get("cores", 0)
        fraction = vm.get("core_fraction", 0)
        core_price = cores * platform.get(fraction) * uptime_daily_hours
        vm["price_core_day"] = core_price
        disk_size = vm.get("disk_size_gb", 0)
        if disk_size is None:
            disk_size = 0
        disk_type = vm.get("disk_type", "none")

        if disk_type == "network-ssd":
            disk_price = disk_size * SSD_GB_PRICE_MONTH
        elif disk_type == "network-ssd-nonreplicated":
            disk_price = disk_size * SSD_NR_GB_PRICE_MONTH
        else:
            disk_price = disk_size * HDD_GB_PRICE_MONTH
        vm["price_disk_month"] = disk_price
        vm["price_disk_day"] = (disk_price / HOURS_MONTH) * 24
        vm["price_total_day"] = vm["price_ram_day"] + vm["price_core_day"] + vm["price_disk_day"]
        # print("VM: {:<60}, Status: {:20}, Price (day): {:6.1f}, Price(day): RAM: {:6.1f}, CPU: {:6.1f},
        # DISK: {:6.1f}". format(vm["name"], vm["status"], vm["price_total_day"], vm["price_ram_day"],
        # vm["price_core_day"], vm["price_disk_day"]))


def calc_total_day_price(vm_list, img_list, snap_list):
    logging.info("calc_total_day_price")

    price_info = dict()
    core_price = 0
    ram_price = 0
    disk_price_month = 0
    disk_price_day = 0
    vm_price = 0
    for vm in vm_list.values():
        core_price = core_price + vm["price_core_day"]
        ram_price = ram_price + vm["price_ram_day"]
        disk_price_month = disk_price_month + vm["price_disk_month"]
        disk_price_day = disk_price_day + vm["price_disk_day"]
        vm_price = vm_price + vm["price_total_day"]
    price_info["price_core_day"] = int(core_price)
    price_info["price_ram_day"] = int(ram_price)
    price_info["price_disk_month"] = int(disk_price_month)
    price_info["price_disk_day"] = int(disk_price_day)
    price_info["price_vm_day"] = int(vm_price)

    img_price_month = 0
    img_price_day = 0
    for img in img_list:
        img_price_month = img_price_month + img["price_image_month"]
        img_price_day = img_price_day + img["price_image_day"]
    price_info["price_image_month"] = int(img_price_month)
    price_info["price_image_day"] = int(img_price_day)

    snap_price_month = 0
    snap_price_day = 0
    for snap in snap_list:
        snap_price_month = snap_price_month + snap["price_snapshot_month"]
        snap_price_day = snap_price_day + snap["price_snapshot_day"]
    price_info["price_snapshot_month"] = int(snap_price_month)
    price_info["price_snapshot_day"] = int(snap_price_day)
    price_info["price_total_day"] = int(vm_price + img_price_day + snap_price_day)
    price_info["price_total_discount"] = price_info["price_total_day"] * DISCOUNT

    return price_info


def create_table():
    logging.info("create_table")

    db.exec('CREATE TABLE IF NOT exists public.vm_info ( '
            'id varchar(50) NOT NULL,'
            '"date" date NULL,'
            'machine_id varchar(25) NULL,'
            '"name" varchar(256) NULL,'
            'fqdn varchar(100) NULL,'
            'ip varchar(30) NULL,'
            'memory_b int8 NULL,'
            'memory_gb int2 NULL,'
            'cores int2 NULL,'
            'core_fraction int2 NULL,'
            'disk_id varchar(30) NULL,'
            'device_name varchar(40) NULL,'
            'disk_type varchar(30) NULL,'
            'disk_size_b int8 NULL,'
            'disk_size_gb int2 NULL,'
            'status varchar(30) NULL,'
            'description varchar(255) NULL,'
            'team varchar(30) NULL,'
            'createdat date NULL,'
            'deletedat date NULL,'
            'creator varchar(100) NULL,'
            'price_ram_day float4 NULL,'
            'price_core_day float4 NULL,'
            'price_disk_month float4 NULL,'
            'price_disk_day float4 NULL,'
            'price_total_day float4 NULL,'
            'uptime_days int4 NULL,'
            'uptime_hours int4 NULL,'
            'uptime_minutes int4 NULL,'
            'autoshutdown varchar(10) NULL,'
            'ttl varchar(30) NULL,'
            'uptime_daily int8 NULL,'
            'today_starttime timestamp NULL,'
            'time_from_last_stop int8 NULL,'
            'stopped_days int4 NULL,'
            'platformid varchar(100) NULL,'
            'CONSTRAINT vm_info_pk PRIMARY KEY (id),'
            'CONSTRAINT vm_info_unique UNIQUE (id));')

    db.exec('CREATE TABLE IF NOT exists public.image_info ('
            'id varchar(35) NULL,'
            '"date" date NULL,'
            '"name" varchar(30) NULL,'
            'createdat date NULL,'
            'description text NULL,'
            '"family" varchar(30) NULL,'
            'storage_size_b int8 NULL,'
            'storage_size_gb int4 NULL,'
            'status varchar(15) NULL,'
            'soft_name varchar(35) NULL,'
            'price_image_month float4 NULL,'
            'price_image_day float4 NULL,'
            'CONSTRAINT image_info_unique UNIQUE (id));')

    db.exec('CREATE TABLE IF NOT exists public.snapshot_info ('
            'id varchar(30) NULL,'
            '"date" date NULL,'
            '"name" varchar(35) NULL,'
            'createdat date NULL,'
            'description text NULL,'
            'storage_size_b int8 NULL,'
            'storage_size_gb int4 NULL,'
            'status varchar(15) NULL,'
            'sourcediskid varchar(30) NULL,'
            'price_snapshot_month float4 NULL,'
            'price_snapshot_day float4 NULL,'
            'CONSTRAINT snapshot_info_unique UNIQUE (id));')

    db.exec('CREATE TABLE IF NOT exists public.price_info ('
            '"date" date NOT NULL,'
            'price_core_day int8 NULL,'
            'price_ram_day int8 NULL,'
            'price_disk_month int8 NULL,'
            'price_disk_day int8 NULL,'
            'price_vm_day int8 NULL,'
            'price_image_month int8 NULL,'
            'price_image_day int8 NULL,'
            'price_snapshot_month int8 NULL,'
            'price_snapshot_day int8 NULL,'
            'price_total_day int8 NULL,'
            'price_total_discount int8 NULL,'
            'CONSTRAINT price_info_pk PRIMARY KEY ("date"));')

    db.exec("CREATE TABLE IF NOT exists public.vm_periods ("
            "id varchar(100) NOT NULL,"
            "vmid varchar(30) NOT NULL,"
            "start_time timestamp NULL,"
            "end_time timestamp NULL,"
            "uptime int8 NULL,"
            "CONSTRAINT vm_periods_pk PRIMARY KEY (id));")

    db.exec("CREATE TABLE IF NOT exists public.vm_snapshot ("
            "vmid varchar(30) NOT NULL,"
            "vm_status varchar(30) NULL,"
            "vm_name varchar(256) NULL,"
            "CONSTRAINT vm_snapshot_pk PRIMARY KEY (vmid));")

    db.exec("CREATE TABLE IF NOT exists public.vm_orphaned_disks ("
            "id varchar(30) NOT NULL,"
            "name varchar(256) NULL,"
            "CONSTRAINT vm_orphaned_disks_pk PRIMARY KEY (id));")


def load_vm_info():
    """
    Загружаем данные из таблички vm_db. Тут важно отметить что за данную дату может не быть еще ни одной записи о
    виртуалках. Это может произойти в силу ряда причин:
     - это первый запуск скрипта за этот день. Например, первый запуск в 00:10:00
     - скрипт свалился в предыдущие дни и больше не запускался. Мы запустили скрипт сегодня первый раз.
    :return:
        Возвращаем словарь с параметрами ВМ, где ключом является vmId
    """
    logging.info(load_vm_info.__name__)

    vm_list_db = dict()
    today = datetime.now().strftime("%Y-%m-%d")
    vm_records = db.get("SELECT id, date, machine_id, name, fqdn, ip, memory_b, memory_gb, cores, "
                        "core_fraction, disk_id, device_name, disk_type, disk_size_b, disk_size_gb, "
                        "status, description, team, createdat, deletedat, creator, price_ram_day, "
                        "price_core_day, price_disk_month, price_disk_day, price_total_day, "
                        "uptime_days, uptime_hours, uptime_minutes, autoshutdown, ttl, "
                        "uptime_daily, today_starttime, time_from_last_stop, stopped_days, "
                        "platform_id FROM vm_info WHERE date = %s", (today,))
    for row in vm_records:
        vm_info = {"date": today, "id": row[2], "name": row[3], "fqdn": row[4], "ip": row[5],
                   "mem_b": row[6], "mem_gb": row[7], "cores": row[8], "core_fraction": row[9], "disk_id": row[10],
                   "device_name": row[11], "disk_type": row[12], "disk_size_b": row[13], "disk_size_gb": row[14],
                   "status": row[15], "description": row[16], "team": row[17], "createdAt": row[18], "deletedAt": row[19],
                   "creator": row[20], "price_ram_day": row[21], "price_core_day": row[22], "price_disk_month": row[23],
                   "price_disk_day": row[24], "price_total_day": row[25], "uptime_days": row[26], "uptime_hours": row[27],
                   "uptime_minutes": row[28], "autoshutdown": row[29], "ttl": row[30], "uptime_daily": row[31],
                   "today_starttime": row[32], "time_from_last_stop": row[33], "stopped_days": row[34],
                   "platform_id": row[35]}
        vm_list_db[vm_info["id"]] = vm_info
    return vm_list_db


def load_vm_snapshot():
    logging.info(load_vm_snapshot.__name__)

    snapshots = dict()
    vm_records = db.get("SELECT vmId, vm_status, vm_name from vm_snapshot")
    for row in vm_records:
        vm_id = row[0]
        status = row[1]
        name = row[2]
        snapshots[vm_id] = (status, name)
    return snapshots


def load_vm_periods():
    logging.info(load_vm_periods.__name__)

    periods = VmDict()
    periods.load(db.get("SELECT vmId, start_time, end_time, uptime from vm_periods"))
    periods.correct()

    return periods


def get_diff_snapshot(vm_cloud, snapshot, period_db):
    """
    Составляем diff всех машин. Diff берется между данными из облака и базки.
    Смотрим что изменилось с момента предыдущего запуска, какие машины были удалены, созданы и т.д.

    :param vm_cloud - список машин полученных из облака
    :param snapshot - свежие данные из таблички vm_snapshot

    :return: словарь со списками изменных машин (дельта с момента последнего запуска):
            - без изменений: продолжают работать (keep_running)
            - без изменений: остаются выключенными (keep_stopped)
            - изменилось состояние: включили (just_started)
            - изменилось состояние: выключили (just_stopped)
            - созданных и работающих (created_running)
            - созданных и остановленных (created_stopped)
            - удаленных (deleted)
    """
    logging.info(get_diff_snapshot.__name__)

    deleted = dict()
    # Список возможных статусов виртуалки: https://yandex.cloud/ru/docs/compute/concepts/vm-statuses
    # Определяем какие машины были созданы, установлены и работают как и прежде
    for vmId, vm_info in vm_cloud.items():
        vmName = vm_info.get("name", "none")
        vmStatus = vm_info.get("status", "unknown")

        if vmId in snapshot:
            snapStatus = snapshot[vmId][0]

            if vmStatus == snapStatus:
                if vmStatus == 'RUNNING':
                    period_db.set_status(vmId, "keep_running")
                else:
                    period_db.set_status(vmId, "keep_stopped")
            else:
                if vmStatus == "RUNNING" and snapStatus == "STOPPED":
                    # ВМ была запущена в 10 минутный период с прошлого запуска.
                    logging.info(f"  started vm: {vmId}; name: {vmName}")
                    period_db.set_status(vmId, "just_started")
                elif vmStatus == "STOPPED" and snapStatus == "RUNNING":
                    # ВМ была остановлена с прошлого запуска скрипта (10 минут)
                    logging.info(f"  stopped vm: {vmId}; name: {vmName}")
                    period_db.set_status(vmId, "just_stopped")
                else:
                    logging.info(f"  other status: vmId: {vmId}; name: {vmName}")
        else:
            # Если ВМ не найдена в snapshot, то значит она недавно создана.
            # But we need set 'start time' only for running machine -> ????????? О чем это????
            if vmStatus == "RUNNING":
                logging.info(f"  created vm (RUNNING now): {vmId}; name: {vmName}")
                period_db.set_status(vmId, "created_running")
            elif vmStatus == "STOPPED":
                logging.info(f"  created vm (STOPPED now): {vmId}; name: {vmName}")
                period_db.set_status(vmId, "created_stopped")
            else:
                logging.warning(f"  created vm ({vmStatus}: {vmId}; name: {vmName}")

    # На данном этапе ищем удаленные машины.
    # Если машина присутствует в vm_snapshot, но ее нет в списке полученном из облака, значит ее удалили уже.
    for snapId in snapshot.keys():
        if snapId not in vm_cloud:
            vmName = snapshot[snapId][1]
            logging.warning(f"  deleted VM: vmId={snapId}; name={vmName}")
            deleted[snapId] = {"name": vmName}
            # в этом случае uptime должен посчитаться (при выставлении end_time в now)
            period_db.set_status(snapId, "deleted")

    return deleted


def update_deleted_vm(vm_deleted, vm_periods_db, db_list, cloud_list):
    logging.info(update_deleted_vm.__name__)

    today = datetime.now().strftime("%Y-%m-%d")
    for vmId in vm_deleted:
        logging.debug(f"Handle vmId={vmId}")
        deleted_info = vm_deleted[vmId]
        vm_info = db_list.get(vmId, None)
        if vm_info:
            vm_info["status"] = "TERMINATED"
            vm_info["deletedAt"] = today
            vm_info["uptime_days"] = deleted_info["uptime_days"]
            vm_info["uptime_hours"] = deleted_info["uptime_hours"]
            vm_info["uptime_minutes"] = deleted_info["uptime_minutes"]
            vm_info["uptime_daily"] = deleted_info["uptime_daily"]
            if vmId in cloud_list:
                logging.error(f"update_deleted_vm: Consistency error: Deleted vmId={vmId} shouldn't be in cloud_list")
            cloud_list[vmId] = vm_info
        vm_periods_db.remove(vmId)
    # Обрабатываем случай когда таблички разъехались: vmId отсутствует в vm_snapshot, но есть в vm_info и vm_periods
    # Отсутствие в vm_snapshot - OK, присутствие в vm_info - OK, а присутствие в vm_periods - косяк - надо удалить!
    to_delete = []
    for vmId in vm_periods_db:
        if vmId not in cloud_list:
            to_delete.append(vmId)
    for id in to_delete:
        vm_periods_db.remove(id)


def init_snapshots_periods(vm_list):
    logging.info("init_snapshots_periods")

    for id, vm in vm_list.items():
        status = vm.get("status")
        start_time = datetime.now()
        if status == "RUNNING":
            db.exec("INSERT INTO vm_periods (vmid, start_time, uptime) "
                    "VALUES (%s, %s, 0) ",
                    (id, start_time))
        elif status == "STOPPED":
            db.exec("INSERT INTO vm_periods (vmid, start_time, end_time, uptime) "
                    "VALUES (%s, %s, %s, 0) ",
                    (id, start_time, start_time))
        db.exec("INSERT INTO vm_snapshot (vmid, vm_status) "
                "VALUES (%s, %s) ",
                (id, status))


def aggregate_uptime(periods, cloud, deleted_vms):
    logging.info(aggregate_uptime.__name__)

    for vmId in periods:
        periods_list = periods[vmId]
        uptime = periods_list.get_total_uptime()
        seconds_in_day = 24 * 60 * 60
        seconds_in_hour = 60 * 60
        days = int(uptime / seconds_in_day)
        hours = int((uptime - (days * seconds_in_day)) / seconds_in_hour)
        minutes = int((uptime - (days * seconds_in_day) - (hours * seconds_in_hour)) / 60)
        vm_info = cloud.get(vmId, None)
        if vm_info:
            vm_info["uptime_days"] = days
            vm_info["uptime_hours"] = hours
            vm_info["uptime_minutes"] = minutes
        elif vmId in deleted_vms:
            deleted_info = deleted_vms[vmId]
            # vmName = deleted_info["name"]
            # print(f"DEBUG: aggregate_uptime: found vmId={vmId}, vmName={vmName} in list of deleted VM")
            deleted_info["uptime_days"] = days
            deleted_info["uptime_hours"] = hours
            deleted_info["uptime_minutes"] = minutes


def aggregate_daily_uptime(cloud_vms, db_vms, deleted_vms):
    logging.info(aggregate_daily_uptime.__name__)
    now = datetime.now()
    for vmId, vm_info in cloud_vms.items():
        cloud_status = vm_info.get("status")
        vm_db = db_vms.get(vmId, 0)
        if vm_db != 0:
            db_status = vm_db.get("status", "unknown")
            today_uptime_seconds = vm_db.get("uptime_daily", 0)
            if today_uptime_seconds is None:  # Может быть для только что запущенной машины
                today_uptime_seconds = 0
            today_latest_start_time = vm_db.get("today_starttime", None)
            if today_latest_start_time is None:
                today_latest_start_time = now
            if cloud_status == "RUNNING":
                if db_status == "RUNNING":
                    today_uptime_seconds = int((now - today_latest_start_time).total_seconds())
                elif db_status == "STOPPED":
                    today_latest_start_time = now
                    pass  # today_uptime_seconds = uptime_daily
            elif cloud_status == "STOPPED":
                if db_status == "RUNNING":
                    today_uptime_seconds = int((now - today_latest_start_time).total_seconds())
                    # today_latest_start_time не меняем, оставляем значение из БД
                elif db_status == "STOPPED":
                    pass
        else:
            # Это новые виртуалки которых еще нет в БД
            today_latest_start_time = now
            today_uptime_seconds = 0
        vm_info["today_starttime"] = today_latest_start_time
        vm_info["uptime_daily"] = today_uptime_seconds

    for vmId, vm in deleted_vms.items():
        vm_db = db_vms.get(vmId, 0)
        logging.debug(f"Handle deleted VM: vmId={vmId}")
        if vm_db != 0:
            today_latest_start_time = vm_db.get("today_starttime", None)
            vm["uptime_daily"] = int((now - today_latest_start_time).total_seconds())
        else:
            vmName = vm.get("name")
            logging.warning(f"No information about deleted VM in vm_info: vmId={vmId}, name={vmName}")


def get_duration_in_stopped_state(vms, periods):
    logging.info(get_duration_in_stopped_state.__name__)
    for vmId in vms:
        vm = vms[vmId]
        status = vm.get("status")
        now = datetime.now()
        total_seconds_in_stop_state = 0
        if status == "STOPPED":
            vmId = vm.get("id")
            vmName = vm.get("name")
            vm_periods = periods.get(vmId)
            if vm_periods is None:
                logging.error("No vmId={vmId}, vmName={vmName} is vm_periods!")
            last_period = periods.get(vmId).last()
            if last_period.is_open():
                logging.error(f"last period for STOPPED vmId={vmId}, vmName={vmName} is OPEN! Check VmDict.set_status!")
            else:
                total_seconds_in_stop_state = int((now - last_period.end_time).total_seconds())
        vm["time_from_last_stop"] = total_seconds_in_stop_state


def save_info_in_db(vm_list, img_list, snap_list, periods_list, unused_disks, price_list):
    logging.info(save_info_in_db.__name__)

    now = datetime.now().strftime("%Y-%m-%d")

    db.exec("BEGIN;")
    db.exec("DELETE FROM vm_periods")
    for vmId in periods_list:
        periods = periods_list[vmId]
        for period in periods:
            start_time = period.start_time
            end_time = period.end_time
            uptime = period.uptime
            key = period.hash
            db.exec("INSERT INTO vm_periods (id, vmid, start_time, end_time, uptime) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE "
                    "SET vmid=EXCLUDED.vmid, start_time=EXCLUDED.start_time, "
                    "end_time=EXCLUDED.end_time, uptime=EXCLUDED.uptime",
                    (key, vmId, start_time, end_time, uptime))

    db.exec("DELETE FROM vm_snapshot")
    for vmId, vm in vm_list.items():
        vmStatus = vm.get("status")
        if vmStatus != "TERMINATED":
            vmName = vm.get("name")
            db.exec("INSERT INTO vm_snapshot (vmid, vm_status, vm_name) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (vmid) DO UPDATE "
                    "SET vm_status=EXCLUDED.vm_status, vm_name=EXCLUDED.vm_name",
                    (vmId, vmStatus, vmName))

    for vmId, vm in vm_list.items():
        id = now + "_" + vm.get("id")
        db.exec("INSERT INTO vm_info (id, date, machine_id, name, fqdn, ip, "
                "memory_b, memory_gb, cores, core_fraction,"
                "disk_id, device_name, disk_type,"
                "disk_size_b, disk_size_gb,"
                "status, description,"
                "team, createdat, deletedat, creator,"
                "price_ram_day,  price_core_day, price_disk_month,"
                "price_disk_day, price_total_day, uptime_days, uptime_hours, uptime_minutes,"
                "autoshutdown, ttl, uptime_daily, today_starttime, time_from_last_stop, stopped_days, platform_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (ID) DO UPDATE "
                "SET date=EXCLUDED.date, machine_id=EXCLUDED.machine_id, name=EXCLUDED.name, "
                "fqdn=EXCLUDED.fqdn, ip=EXCLUDED.ip, "
                "memory_b=EXCLUDED.memory_b, memory_gb=EXCLUDED.memory_gb, "
                "cores=EXCLUDED.cores, core_fraction=EXCLUDED.core_fraction, "
                "disk_id=EXCLUDED.disk_id, device_name=EXCLUDED.device_name, disk_type=EXCLUDED.disk_type, "
                "disk_size_b=EXCLUDED.disk_size_b, disk_size_gb=EXCLUDED.disk_size_gb, "
                "status=EXCLUDED.status, description=EXCLUDED.description, "
                "team=EXCLUDED.team, createdat=EXCLUDED.createdat, deletedat=EXCLUDED.deletedat, "
                "creator=EXCLUDED.creator, price_ram_day=EXCLUDED.price_ram_day, "
                "price_core_day=EXCLUDED.price_core_day, price_disk_month=EXCLUDED.price_disk_month, "
                "price_disk_day=EXCLUDED.price_disk_day, price_total_day=EXCLUDED.price_total_day, "
                "uptime_days=EXCLUDED.uptime_days, uptime_hours=EXCLUDED.uptime_hours, "
                "uptime_minutes=EXCLUDED.uptime_minutes, autoshutdown=EXCLUDED.autoshutdown, ttl=EXCLUDED.ttl,"
                "uptime_daily=EXCLUDED.uptime_daily, today_starttime=EXCLUDED.today_starttime,"
                "time_from_last_stop=EXCLUDED.time_from_last_stop, stopped_days=EXCLUDED.stopped_days,"
                "platform_id=EXCLUDED.platform_id",
                (id, now, vm.get("id"), vm.get("name"), vm.get("fqdn"),
                 vm.get("ip"),
                 vm.get("mem_b"), vm.get("mem_gb"), vm.get("cores"), vm.get("core_fraction"),
                 vm.get("disk_id"), vm.get("device_name"), vm.get("disk_type"),
                 vm.get("disk_size_b"), vm.get("disk_size_gb"),
                 vm.get("status"), vm.get("description"),
                 vm.get("team"), vm.get("createdAt"), vm.get("deletedAt"), vm.get("creator"),
                 vm.get("price_ram_day"), vm.get("price_core_day"), vm.get("price_disk_month"),
                 vm.get("price_disk_day"), vm.get("price_total_day"),
                 vm.get("uptime_days"), vm.get("uptime_hours"), vm.get("uptime_minutes"),
                 vm.get("autoshutdown"), vm.get("ttl"),
                 vm.get("uptime_daily"), vm.get("today_starttime"), vm.get("time_from_last_stop"),
                 vm.get("stopped_days"), vm.get("platform_id")))

    for img in img_list:
        db.exec("INSERT INTO image_info (id, date, name, createdat, description, "
                "family, storage_size_b, storage_size_gb, status, soft_name, "
                "price_image_month, price_image_day) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (ID) DO UPDATE "
                "SET date=EXCLUDED.date, name=EXCLUDED.name, createdat=EXCLUDED.createdat, "
                "description=EXCLUDED.description, family=EXCLUDED.family, "
                "storage_size_b=EXCLUDED.storage_size_b, "
                "storage_size_gb=EXCLUDED.storage_size_gb, status=EXCLUDED.status, "
                "soft_name=EXCLUDED.soft_name, "
                "price_image_month=EXCLUDED.price_image_month, "
                "price_image_day=EXCLUDED.price_image_day",
                (img["id"], now, img["name"], img["createdAt"], img["description"],
                 img["family"], int(img["storage_size_b"]), int(img["storage_size_gb"]),
                 img["status"], img["soft_name"],
                 float(img["price_image_month"]), float(img["price_image_day"])))

    for snapshot in snap_list:
        db.exec("INSERT INTO snapshot_info (id, date, name, createdat, description, "
                "storage_size_b, storage_size_gb, status, sourcediskid, "
                "price_snapshot_month, price_snapshot_day) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE "
                "SET date=EXCLUDED.date, name=EXCLUDED.name, createdat=EXCLUDED.createdat, "
                "description=EXCLUDED.description, storage_size_b=EXCLUDED.storage_size_b, "
                "storage_size_gb=EXCLUDED.storage_size_gb, status=EXCLUDED.status, "
                "sourcediskid=EXCLUDED.sourcediskid, price_snapshot_month=EXCLUDED.price_snapshot_month, "
                "price_snapshot_day=EXCLUDED.price_snapshot_day",
                (snapshot["id"], now, snapshot["name"], snapshot["createdAt"], snapshot["description"],
                 int(snapshot["storage_size_b"]), int(snapshot["storage_size_gb"]),
                 snapshot["status"], snapshot["sourceDiskId"],
                 float(snapshot["price_snapshot_month"]), float(snapshot["price_snapshot_day"])))

    db.exec("DELETE FROM vm_orphaned_disks")
    for diskId, disk_name in unused_disks.items():
        db.exec("INSERT INTO vm_orphaned_disks (id, name) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE "
                "SET name=EXCLUDED.name", (diskId, disk_name))

    db.exec("INSERT INTO price_info (date, price_core_day, price_ram_day, price_disk_month, "
            "price_disk_day, price_vm_day, price_image_month, price_image_day, "
            "price_snapshot_month, price_snapshot_day, price_total_day, price_total_discount) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (DATE) DO UPDATE "
            "SET price_core_day=EXCLUDED.price_core_day, price_ram_day=EXCLUDED.price_ram_day, "
            "price_disk_month=EXCLUDED.price_disk_month, price_disk_day=EXCLUDED.price_disk_day, "
            "price_vm_day=EXCLUDED.price_vm_day, price_image_month=EXCLUDED.price_image_month, "
            "price_image_day=EXCLUDED.price_image_day, price_snapshot_month=EXCLUDED.price_snapshot_month, "
            "price_snapshot_day=EXCLUDED.price_snapshot_day, price_total_day=EXCLUDED.price_total_day,"
            "price_total_discount=EXCLUDED.price_total_discount ",
            (now, price_list["price_core_day"], price_list["price_ram_day"],
             price_list["price_disk_month"], price_list["price_disk_day"], price_list["price_vm_day"],
             price_list["price_image_month"], price_list["price_image_day"],
             price_list["price_snapshot_month"], price_list["price_snapshot_day"],
             price_list["price_total_day"], price_list["price_total_discount"]))

    db.exec("COMMIT;")


def cleanup_db():
    """
        Очищаем записи в базе данных старше шести месяцев
    """
    SIX_MONTHS_DAYS = 182
    today = datetime.now()
    date_six_month_in_past = today - timedelta(days=SIX_MONTHS_DAYS)
    check_date = date_six_month_in_past.strftime("%Y-%m-%d")
    db.exec("DELETE FROM vm_info WHERE date < %s", (check_date,))
    db.exec("DELETE FROM image_info WHERE date < %s", (check_date,))
    db.exec("DELETE FROM snapshot_info WHERE date < %s", (check_date,))


def doublecheck(cloud, periods):
    logging.info(doublecheck.__name__)

    logging.info(f"Len of cloud: {len(cloud)}; {periods.len()}")
    for vmId in periods:
        info = cloud.get(vmId, None)
        if info is None:
            logging.error(f"vmId={vmId} is NOT found in cloud!")
    # print(f"DEBUG: Print all periods")
    # periods.print()


if __name__ == '__main__':
    db = db.Database()
    init_logging()
    logging.info("START")
    create_table()
    get_iam_token(get_jwt_token("meta-stand-sa.json"))
    vm_list_cloud = yc_get_vm_list()

    if os.environ.get("MIGRATION"):
        init_snapshots_periods(vm_list_cloud)
        sys.exit(0)

    snapshot = load_vm_snapshot()
    vm_periods = load_vm_periods()
    vm_list_db = load_vm_info()
    vm_deleted = get_diff_snapshot(vm_list_cloud, snapshot, vm_periods)
    aggregate_uptime(vm_periods, vm_list_cloud, vm_deleted)
    aggregate_daily_uptime(vm_list_cloud, vm_list_db, vm_deleted)
    update_deleted_vm(vm_deleted,
                      vm_periods,
                      vm_list_db,
                      vm_list_cloud)

    orphaned_disks = yc_get_disk_list(vm_list_cloud)
    images_list = yc_get_images()
    snapshot_list = yc_get_snapshots()
    get_duration_in_stopped_state(vm_list_cloud, vm_periods)
    calc_prices_vm(vm_list_cloud)
    price = calc_total_day_price(vm_list_cloud, images_list, snapshot_list)
    save_info_in_db(vm_list_cloud, images_list, snapshot_list, vm_periods, orphaned_disks, price)
    cleanup_db()
    # doublecheck(vm_list_cloud, vm_periods)

    logging.info("FINISH")
    sys.exit(0)
