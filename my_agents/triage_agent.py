from agents import Agent
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from models import RestaurantContext
from my_agents.handoff_utils import make_handoff
from my_agents.menu_agent import menu_agent as _menu_base
from my_agents.order_agent import order_agent as _order_base
from my_agents.reservation_agent import reservation_agent as _res_base

# 1단계: clone 먼저 생성 (handoffs 없이)
menu_agent = _menu_base.clone()
order_agent = _order_base.clone()
reservation_agent = _res_base.clone()

# 2단계: 서로 clone된 버전을 참조하도록 handoffs 설정
# → 어떤 경로로 handoff되어도 항상 handoffs가 살아있는 clone 버전으로 연결
menu_agent.handoffs = [make_handoff(order_agent), make_handoff(reservation_agent)]
order_agent.handoffs = [make_handoff(menu_agent), make_handoff(reservation_agent)]
reservation_agent.handoffs = [make_handoff(menu_agent), make_handoff(order_agent)]

triage_agent = Agent[RestaurantContext](
    name="Triage Agent",
    instructions=f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑 안내 담당자입니다. 고객을 따뜻하게 맞이하고 요청을 파악하여 적절한 전문 담당자에게 연결합니다.

    라우팅 기준:

    🍽️ Menu Agent로 연결:
    - 메뉴 목록, 가격 문의
    - 특정 음식의 재료, 조리 방식 문의
    - 알레르기 정보, 채식/비건 옵션 문의
    - 예: "뭐가 있어요?", "채식 메뉴 있나요?", "달걀 알레르기인데 먹을 수 있는 게 있나요?"

    🛒 Order Agent로 연결:
    - 음식 주문
    - 주문 내역 확인 또는 수정
    - 예: "비빔밥 주세요", "주문하고 싶어요", "뭐 시켰는지 확인해 주세요"

    📅 Reservation Agent로 연결:
    - 테이블 예약
    - 예약 확인 또는 조회
    - 예: "예약하고 싶어요", "자리 있나요?", "예약 확인하고 싶어요"

    판단이 어려울 때는 한 가지 확인 질문을 하고 연결하세요.
    """,
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
    ],
)
