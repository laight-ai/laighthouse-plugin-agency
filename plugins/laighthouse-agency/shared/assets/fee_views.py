"""응답에 맞는 Gross/Net 보기 규칙을 고른다 — fee_basis가 있는 응답은 fees, 없는 옛 응답은 fees_legacy.
fees_legacy를 지울 때는 여기서 옛 경로 분기만 함께 지운다."""
import fees
import fees_legacy


def view(envs, texts, tp):
    """(기본 보기, 서버 기준, 수수료 표). 기본 보기 None = 수수료 없음(토글 없이 원값).
    서버가 fee_basis를 주면 그 기준이 기본이고 수수료 표에 무엇이 있을 때 두 보기를 만든다. 옛 서버면 기준 달 예산에 수수료가 있을 때(tp) 기본 Gross."""
    served = fees.served_basis(envs, texts)
    if served:
        table = fees.fee_table(envs, texts)
        return (served if table else None), served, table
    return ("gross" if fees_legacy.report_has_fee(tp) else None), None, {}


def bundle(default, served, table, sections, alt, summary_name, tp, months):
    """Weekly·Monthly report["basis"] — 두 경로 중 서버 응답에 맞는 것. months = 보고서가 다루는 달("YYYY-MM")."""
    note = f"* {summary_name}는 {fees.LABEL[default]} 기준 숫자로 작성되었습니다."
    if served:
        return fees.served_bundle(served, sections, alt, note, fees.served_fee_note(table, served, months))
    return fees_legacy.basis_bundle(sections, alt, note, fees_legacy.fee_note(tp))


def digest_note(default, served, table):
    return fees.served_digest_note(served, bool(table)) if served else fees_legacy.BASIS_NOTE[bool(default)]
