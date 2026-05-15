"""
Simple household net savings calculator for 2030 based on policy parameters.

Net savings (USD) = efficiency_rebate_per_household_2030
                    - (avg_household_energy_use_mmbtu_annual * cost_increase_per_mmbtu_from_fee_2030)

Positive value means savings; negative means net added annual cost.
"""

def compute_household_net_savings_2030(params):
    rebate = params["efficiency_rebate_per_household_2030"]
    use = params["avg_household_energy_use_mmbtu_annual"]
    delta_cost = params["cost_increase_per_mmbtu_from_fee_2030"]
    return rebate - (use * delta_cost)

if __name__ == "__main__":
    example = {
        "efficiency_rebate_per_household_2030": 150,
        "avg_household_energy_use_mmbtu_annual": 90,
        "cost_increase_per_mmbtu_from_fee_2030": 2
    }
    print(compute_household_net_savings_2030(example))  # -30
