import hashlib
import logging
from datetime import datetime


class Period:
    def __init__(self, start_time, end_time, uptime=0):
        self._start_time = start_time
        self._end_time = end_time
        self._uptime = uptime
        if isinstance(start_time, str):
            try:
                self._start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                raise ValueError("start_time must be in format %Y-%m-%d %H:%M:%S.%f")
        elif isinstance(start_time, datetime):
            pass
        else:
            raise ValueError("start_time & end_time must be of type datetime or str")
        if isinstance(end_time, str):
            try:
                self._end_time = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                raise ValueError("end_time must be in format %Y-%m-%d %H:%M:%S.%f")
        elif isinstance(end_time, datetime):
            pass
        elif end_time is None:
            pass
        else:
            raise ValueError("start_time & end_time must be of type datetime or str")
        # double check uptime and correct in case of any errors
        if self._end_time is not None:
            self._uptime = int((self._end_time - self._start_time).total_seconds())
        if self._end_time is None:
            self._uptime = int((datetime.now() - self._start_time).total_seconds())
            # self._uptime = int(0)
        hash_string = str(self._start_time) + "_" + str(self._end_time) + "_" + str(self.uptime)
        self._period_hash = hashlib.md5(hash_string.encode('utf-8')).hexdigest()

    @property
    def hash(self):
        return self._period_hash

    @property
    def start_time(self):
        return self._start_time

    @start_time.setter
    def start_time(self, value):
        if isinstance(value, str):
            self._start_time = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
        elif isinstance(value, datetime):
            pass
        else:
            raise ValueError("start_time must be of type datetime or str")

    @property
    def end_time(self):
        return self._end_time

    @end_time.setter
    def end_time(self, value):
        if isinstance(value, str):
            try:
                self._end_time = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                raise ValueError("end_time must be in format %Y-%m-%d %H:%M:%S.%f")
        elif isinstance(value, datetime):
            self._end_time = value
        else:
            raise ValueError("end_time must be of type datetime or str")
        if self._end_time is not None:
            self._uptime = int((self._end_time - self._start_time).total_seconds())
        else:
            self._uptime = int((datetime.now() - self._start_time).total_seconds())
        hash_string = str(self._start_time) + "_" + str(self._end_time) + "_" + str(self.uptime)
        self._period_hash = hashlib.md5(hash_string.encode('utf-8')).hexdigest()

    @property
    def uptime(self):
        return self._uptime

    def is_open(self):
        return True if self._end_time is None else False

    def __eq__(self, other):
        return self._period_hash == other.hash

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return (f"  start_time: {self.start_time}; "
                f"end_time: {self.end_time}; "
                f"uptime: {self.uptime}; "
                f"hash: {self._period_hash}")


class PeriodsList:
    def __init__(self, periodsList=None, toCorrect=False):
        self._periods = []
        self._num_open_periods = 0
        if periodsList:
            for item in periodsList:
                if isinstance(item, list):
                    start_time = item[0]
                    end_time = item[1]
                    new_period = Period(start_time, end_time)
                else:
                    new_period = item
                if new_period.is_open():
                    self._num_open_periods += 1
                self.add_period(new_period)
        if toCorrect:
            self.correct()

    def __iter__(self):
        return iter(self._periods)

    def __getitem__(self, item):
        return self._periods[item]

    def __contains__(self, item):
        return item in self._periods

    def __eq__(self, other):
        isEqual = True
        if len(self._periods) != other.len:
            isEqual = False
        else:
            for i in range(len(self._periods)):
                if self._periods[i] != other[i]:
                    isEqual = False
                    break
        return isEqual

    @property
    def len(self):
        return len(self._periods)

    @property
    def num_open(self):
        return self._num_open_periods

    def add_period(self, period):
        self._periods.append(period)
        if period.is_open():
            self._num_open_periods += 1
        # Отсортируем по start_time в порядке убывания
        self._periods.sort(key=lambda i: i.start_time)

    def delete_period(self, period):
        self._periods.remove(period)
        if period.is_open():
            self._num_open_periods -= 1

    def load_periods(self, raw_list, toCorrect=False):
        for item in raw_list:
            start_time = item[0]
            end_time = item[1]
            new_period = Period(start_time, end_time)
            if new_period.is_open():
                self._num_open_periods += 1
            self.add_period(new_period)
        if toCorrect:
            self.correct()

    def last(self):
        return self._periods[-1]

    def first(self):
        return self._periods[0]

    def get_total_uptime(self):
        total_uptime = 0
        for period in self._periods:
            total_uptime += period.uptime
        return total_uptime

    def print(self):
        for period in self._periods:
            print(period)

    def correct(self):
        """
        Делаем предварительную корректировку списка периодов.
        По умолчанию для виртуалки может быть только один открытый период.
        Если есть несколько открытых диапазонов, это сбой - значит по какой-то
        причине не засекли выключения машины и не закрыли диапазон.
        В этом случае удаляем все открытые диапазоны кроме последнего.
        """
        filtered_list = []
        first_open_period = True
        if self._num_open_periods > 1:
            for period in reversed(self._periods):
                if period.is_open():
                    if first_open_period:
                        filtered_list.append(period)
                        first_open_period = False
                    else:
                        pass
                else:
                    filtered_list.append(period)
            filtered_list.reverse()
            self._periods = filtered_list
            self._num_open_periods = 1


class VmDict:
    status_list = ["keep_running",
                   "keep_stopped",
                   "just_started",
                   "just_stopped",
                   "created_running",
                   "created_stopped",
                   "deleted"]

    def __init__(self):
        self._vmDict = dict()

    def __del__(self):
        self._vmDict.clear()

    def __getitem__(self, vmId):
        return self._vmDict[vmId]

    def load(self, stream):
        for item in stream:
            vmId = item[0]  # vmId
            start_time = item[1]  # start_time
            end_time = item[2]  # end_time
            try:
                uptime = item[3]  # uptime
            except IndexError:  # для тестовых целях; в тестах не передаем uptime для краткости
                uptime = 0
            # correct errors in stream
            period = Period(start_time, end_time, uptime)
            vm_periods = self._vmDict.get(vmId)
            if not vm_periods:
                period_list = PeriodsList()
                period_list.add_period(period)
                self._vmDict[vmId] = period_list
            else:
                vm_periods.add_period(period)

    def get(self, vmId):
        return self._vmDict.get(vmId, None)

    def add(self, vmId, period_list):
        self._vmDict[vmId] = period_list

    def remove(self, vmId):
        self._vmDict.pop(vmId, None)

    def correct(self):
        for key in self._vmDict:
            period_list = self._vmDict[key]
            period_list.correct()

    def len(self):
        return len(self._vmDict)

    def print(self):
        print(f"Num of VM: {len(self._vmDict)}")
        for vmId, vm_periods in self._vmDict.items():
            print(f"vmId: {vmId}; periods:")
            for period in vm_periods:
                print(period)

    def set_status(self, vmId, status):
        if status not in self.status_list:
            raise ValueError(f"Unknown status: {status}")
        vm_periods = self._vmDict.get(vmId, None)
        now = datetime.now()
        if vm_periods is not None:
            last_period = vm_periods.last()
            if status == "keep_running":
                if not last_period.is_open():
                    vm_periods.add_period(Period(now, None))
            elif status == "keep_stopped":
                if last_period.is_open():
                    last_period.end_time = now
            elif status == "just_started":
                if last_period.is_open():
                    last_period.start_time = now
                else:
                    vm_periods.add_period(Period(now, None))
            elif status == "just_stopped":
                if last_period.is_open():
                    last_period.end_time = now
            elif status == "deleted":
                if last_period.is_open():
                    last_period.end_time = now
        else:
            if status in ["created_running", "keep_running", "just_started"]:
                self.add(vmId, PeriodsList([Period(now, None), ]))
                # logging.info(f"vmId={vmId} status={status} is not found in vm_periods! Add a new open periods")
            elif status in ["created_stopped", "keep_stopped", "just_stopped"]:
                self.add(vmId, PeriodsList([Period(now, now), ]))
                #logging.info(f"vmId={vmId} status={status} is not found in vm_periods! Add a new closed periods")

    def __iter__(self):
        return iter(self._vmDict)

    def __contains__(self, vmId):
        return vmId in self._vmDict
