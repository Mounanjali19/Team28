"""Transparency Report PDF (EX-05). Rendered only from the stored profile records."""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#14213D")
MUTED = colors.HexColor("#5B6475")
LINE = colors.HexColor("#D5DAE3")
BRAND = colors.HexColor("#0B5CAD")
SOFT = colors.HexColor("#F2F5F9")


def _styles():
    ss = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=18, textColor=INK, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=INK, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK, alignment=TA_LEFT),
        "small": ParagraphStyle("small", parent=ss["BodyText"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
        "label": ParagraphStyle("label", parent=ss["BodyText"], fontName="Helvetica-Bold", fontSize=8, textColor=BRAND, spaceBefore=6),
        "cell": ParagraphStyle("cell", parent=ss["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=INK),
    }


def _table(data, widths, header=True, zebra=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("BACKGROUND", (0, 0), (-1, 0), SOFT)]
    t.setStyle(TableStyle(style))
    return t


def render(profile: dict, contact: dict, whatif: dict | None = None, counterfactual: dict | None = None) -> bytes:
    s = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title="AltCredit Transparency Report", author="AltCredit")
    pol, ml = profile["policy"], profile["ml"]
    P = lambda text, st="body": Paragraph(text, s[st])
    story = [P("AltCredit Transparency Report", "h1"),
             P(f"Applicant {profile['user_id']} ({contact.get('display_name', '')}) &nbsp;|&nbsp; Assessment as of {pol['as_of']} "
               f"&nbsp;|&nbsp; Generated {profile['generated_at'][:19].replace('T', ' ')} UTC &nbsp;|&nbsp; Rule version {pol['rule_version']}", "small"),
             Spacer(1, 6)]

    dec = pol["decision"]
    head = [[P("<b>RULE-BASED POLICY DECISION</b>", "label"), "", ""],
            [P(f"<font size=26><b>{pol['score']}</b></font><font size=10> / 1000</font>"),
             P(f"<b>Risk tier</b><br/>{pol['tier']['code']} {pol['tier']['name']}<br/><font color='#5B6475'>{pol['tier']['meaning']}</font>"),
             P(f"<b>Decision: {dec['label'].upper()}</b><br/>{dec['text']}")]]
    t = Table(head, colWidths=[45 * mm, 50 * mm, 83 * mm])
    t.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0)), ("BOX", (0, 0), (-1, -1), 0.6, BRAND), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (-1, 0), SOFT), ("TOPPADDING", (0, 1), (-1, -1), 6), ("BOTTOMPADDING", (0, 1), (-1, -1), 8)]))
    story += [t, Spacer(1, 4),
              P(profile["explanation"]["summary"] + " The score, tier, eligibility and decision come only from the published rules below.", "small")]

    story.append(P("Rule breakdown (same records that produced the score)", "h2"))
    rows_ = [["Rule", "Factor", "Measured", "Band", "Points"]]
    for r in pol["factors"]:
        rows_.append([r["id"], P(r["name"], "cell"), P(r["value_display"] or "-", "cell"), P(r["band"], "cell"),
                      f"{r['points']:+d} / {r['max'] if r['id'] != '4.2' else '-50'}"])
    rows_.append(["", P("<b>Raw total</b>", "cell"), "", P("capped at 1000" if pol["capped"] else "", "cell"), f"{pol['raw_score']}"])
    rows_.append(["", P("<b>Policy score</b>", "cell"), "", "", f"{pol['score']}"])
    story.append(_table(rows_, [12 * mm, 48 * mm, 30 * mm, 68 * mm, 20 * mm]))

    ex = profile["explanation"]
    story.append(P("Why the score is what it is", "h2"))
    pos = "".join(f"&bull; {x}<br/>" for x in ex["score_increased_because"]) or "&bull; none<br/>"
    neg = "".join(f"&bull; {x}<br/>" for x in ex["score_decreased_because"]) or "&bull; none<br/>"
    story.append(_table([[P("<b>Positive factors</b>", "cell"), P("<b>Negative factors</b>", "cell")], [P(pos, "cell"), P(neg, "cell")]],
                        [89 * mm, 89 * mm]))

    story.append(P("Product eligibility (score &gt;= product minimum)", "h2"))
    prow = [["Product", "Type", "Min score", "Rate", "Status"]]
    rec_ids = [r["product_id"] for r in profile["recommendations"]]
    for p in profile["products"]:
        status = ("Recommended #%d" % (rec_ids.index(p["product_id"]) + 1)) if p["product_id"] in rec_ids else \
                 ("Eligible" if p["eligible"] else f"Locked ({p['gap']} pts short)")
        prow.append([P(p["product_name"], "cell"), p["type"], str(p["min_score"]), p["interest_rate"] or "-", status])
    story.append(_table(prow, [58 * mm, 28 * mm, 20 * mm, 30 * mm, 42 * mm]))

    ml_block = [P("ML Validation Signal (secondary; does not change the policy decision)", "h2")]
    if ml.get("available"):
        ml_block.append(_table([
            ["ML probability of default (12 months)", f"{ml['pd_pct']}%  ({ml['band']} band)"],
            ["ML Risk Score = 1000 x (1 - PD)", f"{ml['ml_risk_score']}  (validation signal, not the credit score)"],
            ["Model confidence", ml["confidence"] + ("" if ml["confident"] else f": {'; '.join(ml['confidence_reasons'])}")],
            ["Rule vs ML", f"{ml['agreement']['label']} (review flag: {ml['agreement']['review_flag']})"],
        ], [70 * mm, 108 * mm], header=False))
        sig = ", ".join(x["label"] for x in ml["risk_increasing_signals"]) or "none"
        ml_block.append(P(f"{ml['agreement']['text']} Main ML risk signals: {sig}.", "small"))
    else:
        ml_block.append(P(ml.get("text", "ML model unavailable."), "small"))
    story.append(KeepTogether(ml_block))

    if counterfactual:
        story.append(P(f"Guidance: how to reach {counterfactual['product']['product_name']}", "h2"))
        story.append(P(counterfactual.get("message", ""), "body"))
        for st in counterfactual.get("steps", []):
            story.append(P(f"&bull; {st['action']} (about {st['expected_points']:+d} points)", "body"))
    if whatif:
        story.append(P("What-If summary (hypothetical, not applied)", "h2"))
        story.append(P(f"Scenario {', '.join(x['type'] for x in whatif['scenarios'])}: {whatif['current']['score']} now, "
                       f"{whatif['simulated']['score']} in {whatif['horizon_months']} month(s) "
                       f"({whatif['delta_vs_current']:+d}; if nothing changes: {whatif['baseline']['score']}).", "body"))

    dq = pol["data_quality"]
    story.append(P("Data quality", "h2"))
    story.append(P(f"Status <b>{dq['status']}</b>, coverage {dq['coverage'] * 100:.0f}% of scored factors, confidence {dq['confidence']}.", "body"))
    for w in dq["warnings"]:
        story.append(P(f"&bull; {w}", "small"))
    story.append(Spacer(1, 8))
    story.append(P("This report is produced by a hackathon prototype using synthetic data only. It is not a legally binding credit decision. "
                   "The policy score is deterministic: the same data and rule version always produce the same result. "
                   f"Open policy decisions applied with rulebook defaults: {', '.join(pol['open_decisions'].keys())}.", "small"))
    doc.build(story)
    return buf.getvalue()
