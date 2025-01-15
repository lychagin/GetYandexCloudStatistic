Для поднятия проекта локально:
1. Устанавливаем виртуальное окружение: python -m venv .venv
2. Запускаем его: .venv\Scripts\Activate.bat
3. Устанавливаем необходимые проекты: pip install -r requirements.txt

Дальше нужны подготовительные меры.

NOTE1: Для того чтобы скрипт заработал, рядом с ним должен лежать файлик meta-stand-sa.json с секретами.
NOTE2: В этой версии скрипта он использует внешнюю базу данных PostgreSql "pg_db".
       Она крутиться в отдельном конейнере и доступна из DataLens.
       В будущем будем использовать "коммунальную" базку.
       Локально у меня поднят конейнер с DataLens и постгрой.
       Чтобы дотянуться до базки pg_db из нашего приложения они должны быть в одной сети.
       
4. Создадим докерную сеть: sudo docker network create cost-net
5. Подключим к ней контейнер с базкой: sudo docker network connect cost-net pg_db
6. Соберем докер-образ из исходников: sudo docker build -t cost-tracker .
7. Стартанем наш контейнер в первый раз и подключим его к сети cost-net: sudo docker run --name cost-tracker --network cost-net cost-tracker
После запуска скрипт вытянет данные из облака и положит в базку pg_db.
Следующие запуски лучше производить с помощью следующей команды, чтобы не плодить контейнеры: sudo docker start cost-tracker

8. Организуем ежедневный запуск скрипта через cron
   8.1. Редактируем наш файл расписания: crontab -e
   8.2. Добавляем следующую запись:
        */10 * * * * /home/sergey/cost-tracker/starter.sh
        
    Таким способом указываем что скрипт должен запускаться каждые 10 минут.
    Скрипт starter.sh запускает наш докер контейнер и проверяет его exit code.
    Скрипт также проверяет докерную сеть cost-net: подключен ли к ней контейнер pg_db (с базой данных).
    Если контейнер не подключен к сети, то подключает.
    Дальше он забрасывает дату запуска скрипта, логи и статус в базку.
    Оттуда данные выгребает дашборд. Таким образом мы на дашборде видем время обновления данных и статус запуска.

9. Для нормальной работы starter.sh установите на машины пакеты для работы с построй из консоли:
   sudo apt install postgresql-client-common
   sudo apt-get install postgresql-client

10. Обеспечьте возможность запуска psql без запроса пароля. Это нужно для работы скрипта.
    Для этого в домашней директории создайте файл .pgpass со следующей строчкой:
    localhost:5433:leadtime:<login>:<password>
    где <login> - логин для postgresql, а <password> - пароль для postgresql
    Ограничьте доступ к файлу: chmod 0600 .pgpass
    
    
Обновление кода на стенде.
1. git pull       - забираем новый код из репозитория
2. ./cleanup.sh   - удаляем старый контейнер и образ
3. ./build.sh     - собираем контейнер, создаем общаю сеть с pg_db запускаем его.
4. ./satrter      - не нужно. Это опциональный шаг, позволяющий запустить контейнер вне расписания

Troubleshooting

1. Найти несколько записей в таблице vm_periods для одной и той же vmId:
   select vmId, count(*) as c from vm_periods vp group by vmid having count(*) > 1 order by c desc

2. Найти все записи в vm_periods для одной и той же машины:
   select * from vm_periods vp where vmid = 'fhm7p82ams6r0v0af6o9' order by start_time

3. Найти все машины с открытыми диапазонами:
   select vmId, count(*) as c from vm_periods vp where end_time is null group by vmid having count(*) > 1 order by c desc

4. Все записи за определенный период:
   select * from vm_periods vp where start_time between '2024-08-06 00:00:00.000' and '2024-08-06 15:00:00.000'

5. Все записи за один день:
   select * from vm_periods vp where start_time > now() - interval '1 day' order by start_time asc