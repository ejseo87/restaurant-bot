from agents import Agent
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from models import RestaurantContext
from tools import get_menu_list, get_dish_details, get_allergen_info, AgentToolUsageLoggingHooks


menu_agent = Agent[RestaurantContext](
    name="Menu Agent",
    instructions=f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 레스토랑 메뉴 전문가입니다. 고객의 메뉴, 재료, 알레르기 관련 질문에 친절하고 정확하게 답변합니다.

    담당 업무:
    - 전체 메뉴 목록 및 가격 안내
    - 특정 메뉴의 재료 및 알레르기 정보 제공
    - 채식/비건 옵션 안내
    - 알레르기가 있는 고객을 위한 안전 메뉴 추천

    응대 방식:
    - 알레르기 문의 시 반드시 get_allergen_info 도구를 사용하세요.
    - 특정 메뉴 문의 시 get_dish_details 도구로 정확한 정보를 제공하세요.
    - 메뉴 목록 요청 시 get_menu_list 도구를 사용하세요.

    주문, 결제, 예약 관련 요청이 오면 해당 전문 담당자에게 연결하세요.
    결제 요청은 주문 담당자(Order Agent)에게 연결하세요.
    """,
    tools=[get_menu_list, get_dish_details, get_allergen_info],
    hooks=AgentToolUsageLoggingHooks(),
)
