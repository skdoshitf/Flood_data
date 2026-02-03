from src.state_machine import AddressVerificationSM, MessageEvent

def test_standard_flow(sm_factory):
    ctx = sm_factory.standard()
    sm = AddressVerificationSM(ctx)
    final = sm.run()
    assert final.logs[-1].startswith("END: Standard")

def test_incomplete_missing_number_to_hitl(sm_factory):
    ctx = sm_factory.incomplete_missing_number()
    sm = AddressVerificationSM(ctx)
    final = sm.run()
    assert any("HITL" in l for l in final.logs)

def test_request_more_info_loopback(sm_factory):
    ctx = sm_factory.incomplete_missing_direction()
    sm = AddressVerificationSM(ctx)
    sm.run()
    sm.handle_message(MessageEvent.CUSTOMER_INFO, {"address": {"direction": "E"}})
    assert any("Customer info received" in l for l in ctx.logs)
