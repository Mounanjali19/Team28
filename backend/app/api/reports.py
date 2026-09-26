"""Transparency Report (PDF) endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.offers_logic import contact_for
from app.api.users import _profile
from app.counterfactual.search import counterfactual
from app.database.db import audit, get_conn
from app.recommendations.products import catalog
from app.reports.transparency import render
from app.security.auth import current_principal
from app.services import get_user_data, user_as_of

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports/{user_id}", summary="Download the Transparency Report PDF", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def report(user_id: str, p: dict = Depends(current_principal)):
    prof = _profile(user_id, p)
    con = get_conn()
    cf = None
    nxt = prof.get("next_locked_product")
    if nxt:
        prods = catalog(con)
        target = next(x for x in prods if x["product_id"] == nxt["product_id"])
        cf = counterfactual(get_user_data(con, user_id), user_as_of(con, user_id), target, prods)
    pdf = render(prof, contact_for(con, user_id, p.get("lender_id"), p["role"]), None, cf)
    audit(con, "report_downloaded", p["sub"], "user", user_id, {"score": prof["policy"]["score"]}, rule_version=prof["policy"]["rule_version"])
    con.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="AltCredit_Transparency_Report_{user_id}.pdf"'})
