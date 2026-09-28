"""A NEW tool written by the Tax team. tax_server.py loads it while running."""

TDS_RATES = {
    "194J": 10.0,  # professional / technical / consulting fees
    "194C": 2.0,   # payments to contractors (companies)
    "194I": 10.0,  # rent of land or building
}


def calculate_tds(amount_inr: float, section: str) -> dict:
    """Calculate TDS (tax deducted at source) on a vendor payment in INR, on the amount BEFORE GST.
    Sections: 194J consulting/professional fees 10%, 194C contractors 2%, 194I rent 10%."""
    rate = TDS_RATES.get(section.upper())
    if rate is None:
        return {"error": f"Known sections: {list(TDS_RATES)}"}
    return {"amount_inr": amount_inr, "section": section, "tds_rate_pct": rate,
            "tds_inr": round(amount_inr * rate / 100, 2)}
