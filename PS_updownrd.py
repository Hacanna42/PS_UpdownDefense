import nextcord
from nextcord.ext import commands
import mysql.connector
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import configparser
import asyncio
import random

with open("apiKey.txt", "r", encoding='UTF-8') as f:
    token = f.read()

# 이 코드는 PoC 버전입니다.


# 사용자별 시작 시간을 저장할 딕셔너리
user_timers = {}
user_timers_start = {}
user_solving = {}


def start_timer(user_id, total_minutes):
    # 현재 시간과 함께 타이머의 만료 시간을 저장
    end_time = datetime.now() + timedelta(minutes=total_minutes)
    start_time = datetime.now()
    user_timers[user_id] = end_time
    user_timers_start[user_id] = start_time


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


def format_elapsed_time(user_id):
    start_time = user_timers_start.get(user_id)
    if start_time:
        elapsed_time = datetime.now() - start_time
        minutes, seconds = divmod(elapsed_time.total_seconds(), 60)
        return f"{int(minutes)}분 {int(seconds)}초"
    else:
        return "ERROR"


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


def get_current_rating(db, discord_id):
    cursor = db.cursor()
    query = "SELECT rating FROM PS_USERINFO WHERE discord_id = %s"
    cursor.execute(query, (discord_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def update_user_info_loss(db, discord_id):
    cursor = db.cursor()
    current_rating = get_current_rating(db, discord_id)
    if current_rating and current_rating > 1:
        update_query = """
        UPDATE PS_USERINFO
        SET solved = solved + 1, rating = rating - 1, now_streak = 0
        WHERE discord_id = %s
        """
        cursor.execute(update_query, (discord_id,))
        db.commit()


def update_user_info_win(db, discord_id):
    cursor = db.cursor()

    # 현재 레이팅과 연승 기록을 가져옴
    cursor.execute(
        "SELECT rating, max_rating, now_streak, max_streak FROM PS_USERINFO WHERE discord_id = %s", (discord_id,))
    result = cursor.fetchone()
    if result:
        current_rating, max_rating, now_streak, max_streak = result
        new_rating = min(current_rating + 1, 31)  # 레이팅은 최대 31로 제한
        new_now_streak = now_streak + 1
        new_max_rating = max(
            current_rating, max_rating) if new_rating > max_rating else max_rating
        new_max_streak = max(new_now_streak, max_streak)

        # 데이터베이스 업데이트
        update_query = """
        UPDATE PS_USERINFO
        SET rating = %s, max_rating = %s, now_streak = %s, max_streak = %s, solved = solved + 1, solved_win = solved_win + 1
        WHERE discord_id = %s
        """
        cursor.execute(update_query, (new_rating, new_max_rating,
                       new_now_streak, new_max_streak, discord_id))
        db.commit()


# 연동 DB 함수
def insert_user_info(db, user_id, handle):  # 연동
    try:
        cursor = db.cursor()
        # 중복 확인
        cursor.execute(
            "SELECT * FROM PS_USERINFO WHERE discord_id = %s OR solvedac_handle = %s",
            (user_id, handle)
        )

        if cursor.fetchone():
            return "**계정과 핸들을 연결할 수 없습니다. 이미 어디선가 등록되어 있습니다. 개발자에게 문의해주세요.**"

        # 데이터 삽입
        query = """
        INSERT INTO PS_USERINFO
        (discord_id, solvedac_handle, rating, max_rating, solved, solved_win, max_streak, now_streak)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (user_id, handle, 6, 6, 0, 0, 0, 0)  # 실버 V로 초기 설정
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
        query = "SELECT solvedac_handle, rating, solved, solved_win, max_rating, max_streak, now_streak FROM PS_USERINFO WHERE discord_id = %s"
        cursor.execute(query, (discord_id,))
        result = cursor.fetchone()

        if result:
            return {
                "solvedac_handle": result[0],
                "rating": result[1],
                "solved": result[2],
                "solved_win": result[3],
                "max_rating": result[4],
                "max_streak": result[5],
                "now_streak": result[6],
            }
        else:
            return "Solved.ac 핸들과 디스코드를 먼저 연동해주세요! **/연동**"
    except mysql.connector.Error as err:
        return f"**데이터베이스 오류가 발생했습니다: {err}**"


bot = commands.Bot()


@bot.event
async def on_ready():
    game = nextcord.Game("업다운 디펜스")
    await bot.change_presence(status=nextcord.Status.online, activity=game)
    print(f'PS 업다운 디펜스 봇이 {bot.user}에 로그인되었습니다.')


# # 백준 푼 문제 크롤링으로 가져오기
# def get_solved_from_boj(boj_user_id):
#     url = f"https://www.acmicpc.net/user/{boj_user_id}"
#     print(url)
#     response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
#     # print(response)

#     if response.status_code != 200:
#         print("BOJ 페이지 요청 실패")
#         return None

#     soup = BeautifulSoup(response.content, 'html.parser')
#     solved_problems = []

#     # "problem-list" 클래스를 가진 div 태그 찾기
#     problem_list_div = soup.find("div", class_="problem-list")
#     if not problem_list_div:
#         print("문제 목록을 찾을 수 없음")
#         return None

#     # 해당 div 내부의 모든 a 태그에서 문제 번호 추출
#     for a_tag in problem_list_div.find_all("a"):
#         problem_number = a_tag.get_text(strip=True)
#         solved_problems.append(problem_number)

#     return solved_problems


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
            max_rating_value = user_info['max_rating']
            icon_url = f"https://ludinf.com/repository/share/PS/tier_{rating_value}.png"

            # 최고 기록 갱신중 ?
            imdick = user_info["max_streak"] == user_info["now_streak"]
            if user_info["now_streak"] < 2:
                imdick = False

            embed.set_thumbnail(url=icon_url)
            embed.add_field(
                name="핸들", value=user_info['solvedac_handle'], inline=True)
            embed.add_field(name="티어", value=get_rank_from_rating(
                rating_value), inline=True)

            # 연승 기록 갱신중이면 불이모지
            회 = "회"
            if imdick:
                회 += " 🔥"
            embed.add_field(name="현재연승", value=str(
                user_info['now_streak'])+회, inline=True)
            embed.add_field(name="시도", value=str(
                user_info['solved']), inline=True)
            embed.add_field(name="승리", value=str(
                user_info['solved_win']), inline=True)
            embed.add_field(name="최고기록", value=get_rank_from_rating(
                max_rating_value), inline=True)
            embed.add_field(name="최고연승", value=str(
                user_info['max_streak'])+"회", inline=True)

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


# 문제 풀이 확인

async def check_problem_solved(boj_user_id, problem_id):
    # Solved.ac API의 반영 시간이 5초 느림
    await asyncio.sleep(6)
    url = f"https://solved.ac/api/v3/search/problem?query=solved_by:{boj_user_id}%20id:{problem_id}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        count = data.get("count", 0)
        return count == 1
    else:
        print(f"API 요청 실패: 상태 코드 {response.status_code}")
        return False


# 아직 풀지 않은 문제를 하나 뽑아서 반환
async def get_unique_problem_id(db, discord_id, boj_user_id, adjust_rating):
    attempts = 0
    while attempts < 5:
        problem_id = get_solved_ac_problem_id(
            db, discord_id, adjust_rating)  # 새로운 문제 ID 가져오기
        if problem_id is None:
            return None

        if not await check_problem_solved(boj_user_id, problem_id):
            return problem_id  # 아직 풀지 않은 문제를 찾은 경우

        print("새로운 시도..")
        attempts += 1

    # 5번동안 문제를 못 찾으면 다음 랭크를 찾기.
    if (adjust_rating < 5):
        print(f"랭크 업 후 찾는중 ....{adjust_rating}")
        return await get_unique_problem_id(db, discord_id, boj_user_id, adjust_rating+1)

    # 루비 레벨까지 아무런 문제도 못 찾았을 경우
    return None


def get_solved_ac_problem_id(db, discord_id, adjust_rating):
    user_info = get_user_info(db, discord_id)
    if isinstance(user_info, dict) and 'rating' in user_info:
        user_rating = user_info['rating']
        user_rating += adjust_rating  # 랭크 조절, 현재 티어의 모든 문제를 풀었을 가능성 고려
        # 루비 보정
        if user_rating >= 28:
            user_rating = 28
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
    # 응답 지연 알림
    await interaction.response.defer()

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
        new_problem_id = await get_unique_problem_id(db, user_id, solvedac_handle, 0)
        if new_problem_id:
            # 문제 찾았으면 게임 시작
            await interaction.followup.send(f"https://boj.ma/{new_problem_id}/t")
            await interaction.followup.send(f"**<제한시간: {t}분>  <@{user_id}>님의 도전이 시작되었습니다.**")
            user_solving[user_id] = {
                "id": new_problem_id, "rating": user_rating}
            start_timer(user_id, t)

        else:
            await interaction.followup.send("**새로운 문제를 찾지 못했습니다. 모든 문제를 풀었거나, 단순히 운이 없었을 수 있습니다. 다시 시도해보세요.**")
    else:
        await interaction.followup.send("**사용자 정보를 가져오는데 실패했습니다.**")
    db.close()


@bot.slash_command(description="업다운 디펜스를 종료합니다.")
async def 종료(interaction: nextcord.Interaction):
    # 응답 지연 알림
    await interaction.response.defer()

    user_id = interaction.user.id
    db = create_db_connection()  # 데이터베이스 연결 생성
    if check_timer_status(user_id):
        # 솔브닥 핸들 가져오기
        boj_user_id = get_user_info(db, user_id)
        if boj_user_id and 'solvedac_handle' in boj_user_id:
            solvedac_handle = boj_user_id['solvedac_handle']

        # 문제 풀었는지 확인하기
        if user_solving[user_id]:
            rating = user_solving[user_id]["rating"]
            if await check_problem_solved(solvedac_handle, user_solving[user_id]["id"]):
                if rating < 31:
                    update_user_info_win(db, user_id)
                    new_rank = get_rank_from_rating(rating + 1)
                    await interaction.followup.send(f"**<@{user_id}>님이 {format_elapsed_time(user_id)}만에 문제를 풀었습니다! {new_rank}로 승급했습니다.**")
                else:
                    await interaction.followup.send(f"**<@{user_id}>님이 {format_elapsed_time(user_id)}만에 문제를 풀었습니다! 그는 신인가요..? 더 이상 받들 곳이 없습니다.**")
            else:
                if rating > 1:
                    update_user_info_loss(db, user_id)
                    new_rank = get_rank_from_rating(rating - 1)
                    await interaction.followup.send(f"**<@{user_id}>님이 문제를 풀지 못했습니다. {new_rank}로 강등됐습니다.**")
                else:
                    await interaction.followup.send(f"**<@{user_id}>님이 문제를 풀지 못했습니다. 더 이상 물러날 곳이 없습니다!!**")
            del user_solving[user_id]
        else:
            await interaction.followup.send(f"**풀고있는 문제가 없습니다.**")

        # 타이머 종료
        end_timer(user_id)
    else:
        if user_id in user_solving:
            update_user_info_loss(db, user_id)
            rating = user_solving[user_id]["rating"]
            if rating > 1:
                await interaction.followup.send(f"**시간 초과. <@{user_id}>님이 {get_rank_from_rating(rating-1)}로 강등됐습니다.**")
            else:
                await interaction.followup.send(f"**<@{user_id}>님이 문제를 풀지 못했습니다. 더 이상 물러날 곳이 없습니다!!**")
            del user_solving[user_id]
        else:
            await interaction.followup.send(f"**풀고있는 문제가 없습니다.**")

    db.close()


@bot.slash_command(description="현재 문제의 남은 시간을 확인합니다.")
async def 남은시간(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    remaining_time = check_timer(user_id)
    if remaining_time:
        minutes, seconds = remaining_time
        await interaction.send(f"**{minutes}분 {seconds}초 남았습니다.**")
    else:
        await interaction.send("**풀고있는 문제가 없습니다.**")


@bot.slash_command(description="현재 풀이중인 문제를 중도포기합니다.")
async def 중도포기(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    db = create_db_connection()  # 데이터베이스 연결 생성
    if user_id in user_solving:
        update_user_info_loss(db, user_id)
        rating = user_solving[user_id]["rating"]
        if rating > 1:
            await interaction.send(f"**<@{user_id}>님이 문제를 중도 포기했습니다. {get_rank_from_rating(rating-1)}로 강등됐습니다.**")
        else:
            await interaction.send(f"**<@{user_id}>님이 문제를 중도 포기했습니다. 어차피 더 내려갈 곳이 없거든요..**")
        del user_solving[user_id]
        del user_timers_start[user_id]
        end_timer(user_id)
    else:
        await interaction.send("**풀고있는 문제가 없습니다.**")
    db.close()


# @bot.slash_command(description="문제를 스킵합니다. (중복 등의 불가피 사유로만 가능)")
# async def 스킵(interaction: nextcord.Interaction):
#     user_id = interaction.user.id
#     end_timer(user_id)
#     await interaction.send("**문제가 스킵되었습니다**")


@bot.slash_command(description="유저 순위를 표시합니다.")
async def 순위(interaction: nextcord.Interaction):
    db = create_db_connection()
    cursor = db.cursor()

    query = """
    SELECT solvedac_handle, rating, max_streak, solved, solved_win
    FROM PS_USERINFO
    ORDER BY rating DESC
    """
    cursor.execute(query)
    rows = cursor.fetchall()

    # 임베드 생성
    embed = nextcord.Embed(
        title="**업다운디펜스 순위**",
        description="*티어가 높은 순으로 정렬된 사용자 순위입니다.*",
        color=0x00ff00
    )

    # 순위 정보를 임베드 필드에 추가
    for idx, row in enumerate(rows, start=1):
        handle, rating, max_streak, solved, solved_win = row
        rank = get_rank_from_rating(rating)
        field_value = f"티어: **{rank}**, 최고연승: **{max_streak}회**, 시도: **{solved}**, 승리: **{solved_win}**"
        embed.add_field(name=f"#{idx} {handle}",
                        value=field_value, inline=False)

    # 푸터 추가
    embed.set_footer(text="업데이트 시간: " +
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    await interaction.send(embed=embed)


# PS계 고수에 대한 찬양 메시지 목록
praises = [
    "여러분, 집중하세요! PS계의 전설, **{}**님의 프로필을 불러왔습니다. 경외심을 품고 바라보세요!",
    "오늘은 특별한 날입니다. 왜냐하면, 우리 가운데 PS계의 거장 **{}**님의 프로필을 불러왔으니까요!",
    "프로그래밍 세계의 왕좌에 오른 **{}**님의 위엄을 느껴보세요. 우리는 그저 감탄만 할 뿐입니다!",
    "코드 한 줄 한 줄이 예술인 **{}**님! 당신의 존재만으로도 우리에겐 영광입니다.",
    "문제 해결의 신, **{}**님! 당신의 앞에서 우리는 모두 초보에 불과합니다.",
    "오늘은 **{}**님이 우리 곁에 계신다는 사실에 감사하며, 그 지혜를 배워야겠습니다.",
    "프로그래밍 문제 앞에서 두려움을 모르는 **{}**님! 당신은 진정한 PS의 천재입니다.",
    "PS계에 영원한 전설로 남을 **{}**님, 당신의 코딩 실력에 경의를 표합니다!",
    "PS계의 달인, **{}**님! 당신의 앞에서 우리는 한없이 작아집니다.",
    "코딩으로 세상을 정복하신 **{}**님, 당신의 위대한 프로필 앞에 박수를 보냅니다!",
    "아아, 세상에! 알고리즘의 정복자, **{}**님의 프로필을 불러오다니! 이것은 실로 영광의 순간입니다!",
    "코딩계의 신, **{}**님의 숨결이 느껴집니다. 우리 모두는 당신의 프로필 앞에 머리를 숙입니다.",
    "정말 믿을 수 없습니다. PS계의 전설, **{}**님이 우리와 같은 채널에! 모두 주목하세요!",
    "단 한 줄의 코드로 세상을 바꾸는 **{}**님, 당신의 천재성 앞에 우리는 그저 감탄할 뿐입니다.",
    "오늘은 역사적인 날입니다, **{}**님과 같은 고수의 프로필이라니! 모두의 시선이 당신에게 집중됩니다!!",
    "알고리즘의 대가, **{}**님이시여! 당신의 프로필에 우리 모두가 환호합니다.",
    "코딩계의 왕자, **{}**님! 당신의 프로필만으로도 이 공간이 빛나고 있습니다.",
    "어둠 속의 빛, **{}**님! 당신의 알고리즘은 언제나 우리에게 길을 안내해줍니다.",
    "PS계의 지배자, **{}**님! 당신의 프로필 앞에서 우리는 그저 작은 존재일 뿐입니다.",
    "어디서도 볼 수 없는 코딩의 귀재, **{}**님의 프로필을 보다니! 우리 모두가 행운아입니다!",
    "아아.. 절대 범접할 수 없는 PS계의 고수 **{}**님의 프로필을 불러왔습니다.."
]


def get_random_praise(handle):
    # 랜덤한 찬사 메시지 선택
    message_template = random.choice(praises)
    return message_template.format(handle)


@bot.slash_command(description="티어 1위 사용자의 프로필을 확인합니다.")
async def 고수(interaction: nextcord.Interaction):
    db = create_db_connection()
    if db is not None:
        cursor = db.cursor()
        query = """
        SELECT solvedac_handle, rating, solved, solved_win, max_rating, max_streak, now_streak
        FROM PS_USERINFO
        ORDER BY rating DESC, solved_win DESC
        LIMIT 1
        """
        cursor.execute(query)
        result = cursor.fetchone()
        if result:
            user_info = {
                "solvedac_handle": result[0],
                "rating": result[1],
                "solved": result[2],
                "solved_win": result[3],
                "max_rating": result[4],
                "max_streak": result[5],
                "now_streak": result[6]
            }

            # 사용자 정보를 임베드로 표시
            embed = nextcord.Embed(title="업다운디펜스 고수", color=0x00ff00)
            icon_url = f"https://ludinf.com/repository/share/PS/tier_{user_info['rating']}.png"
            embed.set_thumbnail(url=icon_url)

            # 임베드 필드 설정
            embed.add_field(
                name="핸들", value=user_info['solvedac_handle'], inline=True)
            embed.add_field(name="티어", value=get_rank_from_rating(
                user_info['rating']), inline=True)
            embed.add_field(
                name="현재연승", value=f"{user_info['now_streak']}회", inline=True)
            embed.add_field(name="시도", value=str(
                user_info['solved']), inline=True)
            embed.add_field(name="승리", value=str(
                user_info['solved_win']), inline=True)
            embed.add_field(name="최고기록", value=get_rank_from_rating(
                user_info['max_rating']), inline=True)
            embed.add_field(
                name="최고연승", value=f"{user_info['max_streak']}회", inline=True)

            await interaction.send(embed=embed)
        else:
            await interaction.send("1위 사용자 정보를 찾을 수 없습니다.")
        db.close()
    else:
        await interaction.send("데이터베이스 연결 실패.")

    await interaction.send(get_random_praise(user_info['solvedac_handle']))


@bot.slash_command(description="업다운 디펜스 도움말")
async def 도움말(interaction: nextcord.Interaction):
    await interaction.send("```ansi\n[1;2m[1;37m[1;36m[1;31m[1;34m업다운 디펜스에 오신 것을 환영합니다![0m[1;31m[0m[1;36m[0m[1;37m\n현재 디펜스 티어에 맞는 문제들이 랜덤하게 출제됩니다. 문제를 맞추면 승급하고, 그렇지 못하면 강등됩니다. 첫 시작 티어는 실버 V 입니다.\n\n[1;2m[1;37m/연동 (솔브닥ID)[0m[0m - 디스코드 계정과 Solved.ac 계정을 연동합니다.\n[1;2m[1;37m/프로필[0m[0m - 내 프로필을 확인합니다.\n[1;2m[1;37m/시작[0m[0m - 현재 디펜스티어에 맞는 문제가 출제됩니다. 디펜스 시작!\n[1;2m[1;37m/종료[0m[0m - 디펜스를 종료합니다. 성공/실패 여부에 따라 티어가 변동합니다.\n[1;2m[1;37m/중도포기[0m[0m - 문제 풀이 중간에 포기할 수 있습니다.\n[1;2m[1;37m/남은시간[0m[0m - 남은 시간을 확인할 수 있습니다.\n[2;37m[1;37m/순위[0m[2;37m[0m - 디펜스티어 순위를 볼 수 있습니다.\n[1;2m[1;31m/고수[0m[0m - 현재 1등의 프로필을 확인합니다.```")

bot.run(token)
