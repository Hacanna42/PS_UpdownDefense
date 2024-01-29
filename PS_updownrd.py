import nextcord
from nextcord.ext import commands
import mysql.connector
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import configparser

with open("apiKey.txt", "r", encoding='UTF-8') as f:
    token = f.read()

# 이 코드는 PoC 버전입니다.


# 사용자별 시작 시간을 저장할 딕셔너리
user_timers = {}
user_solved = {}


def start_timer(user_id, total_minutes):
    # 현재 시간과 함께 타이머의 만료 시간을 저장
    end_time = datetime.now() + timedelta(minutes=total_minutes)
    user_timers[user_id] = end_time


def end_timer(user_id):
    # 타이머 삭제
    if user_id in user_timers:
        del user_timers[user_id]
        return "타이머가 종료되었습니다."
    else:
        return "활성화된 타이머가 없습니다."


def check_timer(user_id):
    # 현재 시간과 타이머의 만료 시간을 비교하여 남은 시간 계산
    end_time = user_timers.get(user_id)
    if end_time:
        remaining_time = end_time - datetime.now()
        if remaining_time.total_seconds() > 0:
            minutes, seconds = divmod(remaining_time.total_seconds(), 60)
            return int(minutes), int(seconds)
        else:
            return 0, 0
    else:
        return None


def check_timer_status(user_id):
    end_time = user_timers.get(user_id)
    if end_time:
        remaining_time = end_time - datetime.now()
        if remaining_time.total_seconds() > 0:
            return True
        else:
            return False
    else:
        return False

# DB 연결 함수


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


# 연동 DB 함수
def insert_user_info(db, user_id, handle):  # 연동
    try:
        cursor = db.cursor()
        # 중복 확인
        cursor.execute(
            "SELECT * FROM PS_USERINFO WHERE discord_id = %s", (user_id,))
        if cursor.fetchone():
            return "**디스코드 계정이 이미 다른 Solved.ac 계정과 연동되어 있습니다. 개발자에게 문의해주세요.**"

        # 데이터 삽입
        query = "INSERT INTO PS_USERINFO (discord_id, solvedac_handle, rating, solved, solved_win) VALUES (%s, %s, %s, %s, %s)"
        values = (user_id, handle, 6, 0, 0)  # 실버 V
        cursor.execute(query, values)
        db.commit()
        return "**Solved.ac 계정이 연동되었습니다.**"
    except mysql.connector.Error as err:
        db.rollback()
        return f"**오류가 발생했습니다: {err}**"


# 프로필 조회 DB 함수
def get_user_info(db, discord_id):
    try:
        cursor = db.cursor()
        query = "SELECT solvedac_handle, rating, solved, solved_win FROM PS_USERINFO WHERE discord_id = %s"
        cursor.execute(query, (discord_id,))
        result = cursor.fetchone()

        if result:
            return {
                "solvedac_handle": result[0],
                "rating": result[1],
                "solved": result[2],
                "solved_win": result[3]
            }
        else:
            return "Solved.ac 핸들과 디스코드를 먼저 연동해주세요! **/연동**"
    except mysql.connector.Error as err:
        return f"**데이터베이스 오류가 발생했습니다: {err}**"


bot = commands.Bot()


@bot.event
async def on_ready():
    print(f'PS 업다운 디펜스 봇이 {bot.user}에 로그인되었습니다.')


# 백준 푼 문제 가져오기
def get_solved(user_id):
    """
    정보 조회 - user_id를 입력하면 백준 사이트에서 해당 user가 푼 총 문제수, 문제들 정보(level 높은 순)를 튜플(int, list)로 반환해줌.
    :param str user_id: 사용자id
    :return: 내가 푼 문제수, 내가 푼 문제들 정보
    :rtype: int, list
    """
    url = f"https://solved.ac/api/v3/search/problem?query=solved_by%3A{user_id}&sort=level&direction=desc"
    r_solved = requests.get(url)
    if r_solved.status_code == requests.codes.ok:
        solved = json.loads(r_solved.content.decode('utf-8'))

        count = solved.get("count")

        items = solved.get("items")
        solved_problems = []
        for item in items:
            solved_problems.append(
                {
                    'problemId': item.get("problemId"),
                    'titleKo': item.get("titleKo"),
                    'level': item.get("level"),
                }
            )
        # print("푼 문제수와 젤 고난이도 문제 1개만 >>>", count, solved_problems[0])
    else:
        print("푼 문제들 요청 실패")
    return count, solved_problems


# 백준 푼 문제 크롤링으로 가져오기
def get_solved_from_boj(boj_user_id):
    url = f"https://www.acmicpc.net/user/{boj_user_id}"
    print(url)
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    # print(response)

    if response.status_code != 200:
        print("BOJ 페이지 요청 실패")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')
    solved_problems = []

    # "problem-list" 클래스를 가진 div 태그 찾기
    problem_list_div = soup.find("div", class_="problem-list")
    if not problem_list_div:
        print("문제 목록을 찾을 수 없음")
        return None

    # 해당 div 내부의 모든 a 태그에서 문제 번호 추출
    for a_tag in problem_list_div.find_all("a"):
        problem_number = a_tag.get_text(strip=True)
        solved_problems.append(problem_number)

    return solved_problems


# 연동 메서드
@bot.slash_command(description="Solved.ac 계정 핸들과 디스코드 계정을 연결합니다.")
async def 연동(interaction: nextcord.Interaction, 핸들: str = nextcord.SlashOption(required=True, description="Solved.ac 핸들을 입력하세요")):
    user_id = interaction.user.id
    db = create_db_connection()

    if db is not None:
        result = insert_user_info(db, user_id, 핸들)
        await interaction.send(result)
        db.close()
    else:
        await interaction.send("DB 연결 실패. :(")

# 프로필 랭크 반환 함수


def get_rank_from_rating(rating):
    ranks = ["브론즈", "실버", "골드", "플래티넘", "다이아몬드", "루비"]
    roman_numerals = ["V", "IV", "III", "II", "I"]

    if rating == 31:
        return "마스터"
    elif 1 <= rating <= 30:
        index = (rating - 1) // 5
        sub_rank_index = (rating - 1) % 5
        return f"{ranks[index]} {roman_numerals[sub_rank_index]}"
    else:
        return "유효하지 않은 레이팅"


# 프로필 메서드
@bot.slash_command(description="나의 프로필을 확인합니다.")
async def 프로필(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    db = create_db_connection()
    if db is not None:
        user_info = get_user_info(db, user_id)
        if isinstance(user_info, dict):
            # 사용자 정보가 정상적으로 검색되었을 때의 처리
            # 임베드 생성
            embed = nextcord.Embed(title="업다운디펜스", color=0x00ff00)
            rating_value = user_info['rating']
            icon_url = f"https://ludinf.com/repository/share/PS/tier_{rating_value}.png"
            embed.set_thumbnail(url=icon_url)
            embed.add_field(
                name="핸들", value=user_info['solvedac_handle'], inline=True)
            embed.add_field(name="레이팅", value=get_rank_from_rating(
                rating_value), inline=True)
            embed.add_field(name="시도", value=str(
                user_info['solved']), inline=True)
            embed.add_field(name="승리", value=str(
                user_info['solved_win']), inline=True)
            # 필요한 경우 더 많은 필드를 추가할 수 있습니다.

            # 임베드를 포함한 메시지 전송
            await interaction.send(embed=embed)
        else:
            # 오류 메시지 또는 사용자 정보가 없는 경우의 처리
            await interaction.send(user_info)
        db.close()
    else:
        await interaction.send("데이터베이스 연결 실패.")


@bot.slash_command(description="푼 문제를 미리 등록해서, 중복 문제가 출제되지 않도록 합니다.")
async def 푼문제등록(interaction: nextcord.Interaction):
    await interaction.send("**이미 자동으로 푼 문제가 모두 등록되었습니다.**")


# 티어 형식
def get_query_for_numeric_rating(rating):
    if not 1 <= rating <= 31:
        return "유효하지 않은 레이팅"

    ranks = ["b", "s", "g", "p", "d", "r"]
    if rating >= 28:
        return "r4"  # 마스터 등급
    else:
        index = (rating - 1) // 5
        sub_rank = 5 - (rating - 1) % 5
        return f"{ranks[index]}{sub_rank}"

# 문제 선택


def get_new_unique_problem(db, discord_id, boj_user_id):
    solved_problems = get_solved_from_boj(boj_user_id)  # 이미 해결한 문제들 가져오기
    user_solved[discord_id] = len(solved_problems)
    if solved_problems is None:
        return None  # 크롤링 실패 시 None 반환

    solved_problem_ids = set(solved_problems)
    print(solved_problem_ids)

    count = 0
    while True:
        problem_id = get_solved_ac_problem_id(db, discord_id)  # 새로운 문제 ID 가져오기
        if problem_id is None:
            count += 1
            return None  # 문제 가져오기 실패

        if str(problem_id) not in solved_problem_ids:
            return problem_id  # 겹치지 않는 문제 발견

        if count > 10:
            return None


def get_solved_ac_problem_id(db, discord_id):
    user_info = get_user_info(db, discord_id)
    if isinstance(user_info, dict) and 'rating' in user_info:
        user_rating = user_info['rating']
        query_level = get_query_for_numeric_rating(user_rating)
        url = f"https://solved.ac/api/v3/search/random_problem?query=*{query_level}%20s%23100..%20%25ko"

        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get("problemId")  # "problemId" 키의 값을 반환
        else:
            print(f"API 요청 실패: 상태 코드 {response.status_code}")
            return None
    else:
        return None  # 유저 정보를 얻지 못한 경우


@bot.slash_command(description="업다운 디펜스를 시작합니다.")
async def 시작(interaction: nextcord.Interaction):
    db = create_db_connection()  # 데이터베이스 연결 생성
    user_id = interaction.user.id
    # 사용자의 solved.ac 핸들 가져오기
    user_info = get_user_info(db, user_id)
    if user_info and 'solvedac_handle' in user_info and 'rating' in user_info:
        solvedac_handle = user_info['solvedac_handle']
        user_rating = user_info['rating']

        # 타이머 조정
        t = (user_rating - 11) * 5 + 30
        if t < 30:
            t = 30

        # 새로운 유니크한 문제 ID 가져오기
        new_problem_id = get_new_unique_problem(db, user_id, solvedac_handle)
        if new_problem_id:
            # 문제 찾았으면 게임 시작
            await interaction.send(f"https://boj.ma/{new_problem_id}/t")
            await interaction.send(f"**제한시간 {t}분이 시작되었습니다!**")
            start_timer(user_id, t)
            # print(f"새로운 문제 ID: {new_problem_id}")
        else:
            await interaction.send("**새로운 문제를 찾지 못했습니다. 모든 문제를 풀었거나, 단순히 운이 없었을 수 있습니다. 다시 시도해보세요.**")
    else:
        await interaction.send("**사용자 정보를 가져오는데 실패했습니다.**")
    db.close()


# 문제 실패 (레이팅 하락)
def update_user_info_loss(db, discord_id):
    cursor = db.cursor()
    query = """
    UPDATE PS_USERINFO 
    SET solved = solved + 1, rating = rating - 1
    WHERE discord_id = %s
    """
    cursor.execute(query, (discord_id,))
    db.commit()

# 문제 성공 (레이팅 상승)


def update_user_info_win(db, discord_id):
    cursor = db.cursor()
    query = """
    UPDATE PS_USERINFO 
    SET solved = solved + 1, rating = rating + 1, solved_win = solved_win + 1
    WHERE discord_id = %s
    """
    cursor.execute(query, (discord_id,))
    db.commit()


@bot.slash_command(description="업다운 디펜스를 종료합니다.")
async def 종료(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    db = create_db_connection()  # 데이터베이스 연결 생성
    start_solved_count = user_solved.get(user_id, 0)
    if check_timer_status(user_id):
        boj_user_id = get_user_info(db, user_id)
        if boj_user_id and 'solvedac_handle' in boj_user_id:
            solvedac_handle = boj_user_id['solvedac_handle']
        current_solved_count = len(get_solved_from_boj(solvedac_handle))
        if current_solved_count > start_solved_count:
            update_user_info_win(db, user_id)
            await interaction.send(f"**문제를 풀었습니다! 티어가 상승합니다.**")
        else:
            update_user_info_loss(db, user_id)
            await interaction.send(f"**문제를 풀지 못했습니다. 티어가 하락합니다.**")
        end_timer(user_id)
    else:
        update_user_info_loss(db, user_id)
        await interaction.send("**시간 초과. 티어가 하락합니다.**")
    db.close()


@bot.slash_command(description="현재 문제의 남은 시간을 확인합니다.")
async def 남은시간(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    remaining_time = check_timer(user_id)
    if remaining_time:
        minutes, seconds = remaining_time
        await interaction.send(f"**남은 시간: {minutes}분 {seconds}초**")
    else:
        await interaction.send("**풀고있는 문제가 없습니다.**")


@bot.slash_command(description="현재 풀이중인 문제를 중도포기합니다.")
async def 중도포기(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    db = create_db_connection()  # 데이터베이스 연결 생성
    update_user_info_loss(db, user_id)
    end_timer(user_id)
    await interaction.send("**문제를 중도 포기했습니다. 레이팅이 하락했습니다.**")
    db.close()


@bot.slash_command(description="문제를 스킵합니다. (중복 등의 불가피 사유로만 가능)")
async def 스킵(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    end_timer(user_id)
    await interaction.send("**문제가 스킵되었습니다**")


@bot.slash_command(description="유저 순위를 표시합니다.")
async def 순위(interaction: nextcord.Interaction):
    db = create_db_connection()  # 데이터베이스 연결 생성
    cursor = db.cursor()

    query = """
    SELECT solvedac_handle, rating, solved, solved_win
    FROM PS_USERINFO
    ORDER BY rating DESC
    """
    cursor.execute(query)
    rows = cursor.fetchall()

    # 임베드 생성
    embed = nextcord.Embed(
        title="업다운디펜스 순위", description="티어가 높은순으로 정렬합니다.", color=0x00ff00)

    # 순위 정보를 임베드 필드에 추가
    for idx, row in enumerate(rows, start=1):
        embed.add_field(
            name=f"{idx}. {row[0]}", value=f"티어: {get_rank_from_rating(row[1])}, 시도: {row[2]}, 승리: {row[3]}", inline=False)

    await interaction.send(embed=embed)

bot.run(token)
