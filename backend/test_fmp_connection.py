
from app.services.stock_universe.fmp_client import (
    FMPClient,
    FMPClientError,
)


def main():
    print("Testing Financial Modeling Prep connection...")

    try:
        client = FMPClient()

        companies = client.get_company_screener(
            page=0,
            limit=10,
        )

        print(f"\nSuccessfully retrieved {len(companies)} companies.")

        if not companies:
            print("Warning: FMP returned an empty result.")
            return

        print("\nSample companies:")

        for company in companies[:5]:
            print(
                f"{company.get('symbol')} | "
                f"{company.get('companyName')} | "
                f"{company.get('sector')} | "
                f"Market cap: {company.get('marketCap')}"
            )

        print("\nFMP connection test passed.")

    except FMPClientError as exc:
        print(f"\nFMP connection failed: {exc}")


if __name__ == "__main__":
    main()
