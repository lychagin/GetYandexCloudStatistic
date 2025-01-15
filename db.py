import psycopg2
import platform
import yaml


class Database:
    DATABASE = {
        'DB_NAME': 'leadtime',
        'DB_LOGIN': 'root',
        'DB_PASSWORD': 'root',
        'DB_HOST': 'localhost',
        'DB_PORT': 5433
    }

    def __init__(self):
        linux = "db_settings.linux.yaml"
        windows = "db_settings.windows.yaml"
        filename = ""

        if platform.system() == "Windows":
            filename = windows
        else:
            filename = linux

        with open(filename) as config:
            params = yaml.safe_load(config)

        self.DATABASE["DB_NAME"] = params["db_name"]
        self.DATABASE["DB_LOGIN"] = params["db_login"]
        self.DATABASE["DB_PASSWORD"] = params["db_password"]
        self.DATABASE["DB_HOST"] = params["db_host"]
        self.DATABASE["DB_PORT"] = params["db_port"]

        try:
            self.conn = psycopg2.connect(
                database=self.DATABASE['DB_NAME'],
                user=self.DATABASE['DB_LOGIN'],
                password=self.DATABASE['DB_PASSWORD'],
                host=self.DATABASE['DB_HOST'],
                port=self.DATABASE['DB_PORT'])
        except Exception as err:
            logging.error(f'An exception has occurred: {err}')
            raise err
        if self.conn is not None:
            self.cur = self.conn.cursor()

    def __del__(self):
        self.cur.close()
        self.conn.close()

    def exec(self, query, data=[]):
        self.cur.execute(query, data)
        self.conn.commit()

    def get(self, query, data=[]):
        self.cur.execute(query, data)
        return self.cur.fetchall()
