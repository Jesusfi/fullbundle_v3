import datetime as dt
from sqlalchemy.orm import Session
from sqlalchemy import select
from models import Holding, Assumptions, PriceCache, Projection, ProjectionPoint

# --- helpers ---
def per_month_rate(annual_pct: float) -> float:
    r = max(0.0, (annual_pct or 0.0) / 100.0)
    return (1 + r) ** (1 / 12) - 1

def add_months(d: dt.date, n: int) -> dt.date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    day = 1  # we always label the first of the month
    return dt.date(y, m, day)

def first_of_next_month(today: dt.date) -> dt.date:
    return add_months(dt.date(today.year, today.month, 1), 1)

def run_projection_for_user(user, db: Session):
    asm = db.scalar(select(Assumptions).where(Assumptions.user_id == user.id))
    rows = db.scalars(select(Holding).where(Holding.user_id == user.id)).all()

    # --- current values (today) ---
    values = []
    for h in rows:
        if h.type == "cash":
            values.append(float(h.units))
        elif h.type == "ticker":
            px = float(h.price or 0.0)
            if px <= 0:
                cached = db.scalar(
                    select(PriceCache)
                    .where(PriceCache.user_id == user.id, PriceCache.ticker == h.name.upper())
                )
                px = float(getattr(cached, "price", 0.0) or 0.0)
            values.append(h.units * px if px > 0 else 0.0)
        else:  # cagr-only: units == current value
            values.append(float(h.units))

    start_total = sum(values)

    # fixed weights for global contribution (stable plan)
    if start_total > 0:
        fixed_w = [v / start_total for v in values]
    else:
        fixed_w = [1.0 / max(1, len(values)) for _ in values]

    # per-holding monthly rates & contributions
    m_rates = [
        per_month_rate(asm.cash_apy if h.type == "cash" else (h.cagr or asm.default_cagr))
        for h in rows
    ]
    per_h_m_contrib = [(h.monthly_contrib or 0.0) for h in rows]
    global_m_contrib = (asm.monthly_contrib or 0.0)

    # --- monthly simulation anchored to calendar months ---
    months = 65 * 12
    table: list[tuple[str, float]] = []
    checkpoints: list[tuple[int, float]] = [(0, start_total)]
    millionaire_date: dt.datetime | None = None
    millionaire_month_index: int | None = None  # <--- add this

    label0 = first_of_next_month(dt.date.today())
    total = start_total

    for m in range(months):
        # compound one month
        for i in range(len(values)):
            values[i] *= (1.0 + m_rates[i])

        # add contributions at month-end
        for i in range(len(values)):
            values[i] += global_m_contrib * fixed_w[i]
            values[i] += per_h_m_contrib[i]

        total = sum(values)

        label_date = add_months(label0, m)
        table.append((label_date.isoformat(), total))

        approx_days = int(round((m + 1) * (365 / 12)))
        if approx_days in (30, 90, 180, 365, 730, 1095):
            checkpoints.append((approx_days, total))

        if millionaire_date is None and total >= asm.target:
            millionaire_date = dt.datetime.combine(label_date, dt.time.min)
            millionaire_month_index = m  # <--- record the month index

    # ---- compute days_to_target robustly ----
    days_to_target = (
        int(round((millionaire_month_index + 1) * (365 / 12)))  # +1 because m is 0-based
        if millionaire_month_index is not None else None
    )

    # persist projection
    p = Projection(
        user_id=user.id,
        run_at=dt.datetime.utcnow(),
        start_total=start_total,
        target=asm.target,
        basis=12,
        millionaire_date=millionaire_date,
        days_to_target=days_to_target,  # <--- use the robust value
    )
    db.add(p); db.commit(); db.refresh(p)

    keep = {0, 30, 90, 180, 365, 730, 1095}
    for d, tot in checkpoints:
        if d in keep:
            db.add(ProjectionPoint(projection_id=p.id, day=d, total=tot))
    db.commit()

    return {
        "run_at": p.run_at,
        "start_total": start_total,
        "target": asm.target,
        "basis": 12,
        "millionaire_date": millionaire_date,
        "days_to_target": p.days_to_target,
        "checkpoints": checkpoints,
        "table": table,  # <-- monthly 65-year table: [("YYYY-MM-01", total), ...]
    }
