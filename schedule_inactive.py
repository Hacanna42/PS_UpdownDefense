from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import mysql.connector
import pytz
from apscheduler.triggers.cron import CronTrigger
import configparser


def create_db_connection():
    # 구성 파일 읽기
    config = configparser.ConfigParser()
    config.read('config.ini')

    db_config = config['database']
    db = mysql.connector.connect(
        host=db_config.get('host'),
        user=db_config.get('user'),
        passwd=db_config.get('password'),
        database=db_config.get('database')
    )
    return db


def decrease_rating_for_inactive_users():
    db = create_db_connection()
    cursor = db.cursor()

    # 일주일 이상 플레이하지 않은 골드 이상 유저의 레이팅 감소
    query = """
    UPDATE PS_USERINFO
    SET rating = GREATEST(1, rating - 1)
    WHERE last_played < NOW() - INTERVAL 7 DAY
    AND rating > 10
    """

    cursor.execute(query)
    db.commit()
    print(f"Rating updated for inactive users at {datetime.now()}")

    cursor.close()
    db.close()


# decrease_rating_for_inactive_users()
scheduler = BackgroundScheduler()
scheduler.add_job(decrease_rating_for_inactive_users, trigger=CronTrigger(
    hour=0, minute=0, second=0, timezone='Asia/Seoul'))

scheduler.start()
