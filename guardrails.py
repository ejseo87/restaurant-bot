from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    Runner,
    input_guardrail,
    output_guardrail,
)

from models import (
    InputGuardRailOutput,
    OutputGuardRailOutput,
    RestaurantContext,
)


input_guardrail_agent = Agent[RestaurantContext](
    name="Restaurant Input Guardrail",
    instructions="""
    당신은 레스토랑 봇의 안전 담당자입니다. 사용자의 최신 메시지를 확인하고 아래 기준으로 판별하세요.

    - is_off_topic: 레스토랑 이용, 메뉴, 주문, 예약, 불만 접수와 무관하다면 true.
    - contains_abuse: 욕설, 차별, 위협 등 부적절한 언어가 포함되면 true.
    - reason: 한국어로 간단히 사유 요약.

    둘 다 해당되지 않으면 false로 설정하고 reason은 "정상 입력" 정도로 남기세요.
    JSON으로만 답하세요.
    """,
    output_type=InputGuardRailOutput,
)


@input_guardrail(run_in_parallel=False)
async def restaurant_input_guardrail(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
    user_input,
):
    result = await Runner.run(
        input_guardrail_agent,
        user_input,
        context=wrapper.context,
    )

    output = result.final_output
    triggered = output.is_off_topic or output.contains_abuse

    if triggered:
        state = wrapper.context.guardrail_state
        state.last_violation_type = "abuse" if output.contains_abuse else "off_topic"
        state.last_violation_reason = output.reason
        state.blocked_attempts += 1

    return GuardrailFunctionOutput(
        output_info=output,
        tripwire_triggered=triggered,
    )


output_guardrail_agent = Agent[RestaurantContext](
    name="Restaurant Output Guardrail",
    instructions="""
    다음은 레스토랑 봇이 고객에게 보내려는 답변입니다. 아래 항목을 평가해 JSON으로만 응답하세요.

    - is_professional: 공손하고 공감적이며 지침에 맞다면 true, 거칠거나 부적절하면 false.
    - reveals_internal_info: 내부 운영 세부사항, 직원 개인정보, 시스템 정책 등을 노출하면 true.
    - makes_unverified_claims: 메뉴/정책에 없는 정보나 확인되지 않은 약속을 하면 true.
    - reason: 문제가 있다면 무엇을 수정해야 하는지 간단히 설명.
    """,
    output_type=OutputGuardRailOutput,
)


@output_guardrail
async def restaurant_output_guardrail(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
    output: str,
):
    result = await Runner.run(
        output_guardrail_agent,
        output,
        context=wrapper.context,
    )

    validation = result.final_output
    triggered = (
        (not validation.is_professional)
        or validation.reveals_internal_info
        or validation.makes_unverified_claims
    )

    if triggered:
        state = wrapper.context.guardrail_state
        state.last_violation_type = "output_violation"
        state.last_violation_reason = validation.reason
        state.blocked_attempts += 1

    return GuardrailFunctionOutput(
        output_info=validation,
        tripwire_triggered=triggered,
    )
