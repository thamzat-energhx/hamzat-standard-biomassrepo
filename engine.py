"""EnerghxPLUS AD–HTC–EMCV deterministic prescriptive DSS.
Scientific parameters from the manuscript are separated from runtime/operator policy inputs.
"""
from itertools import product

VEHICLES = [
    {"id":"tricycle","capacity_kg":450.0,"cost_ngn":3750.0,"time_min":45.0},
    {"id":"van","capacity_kg":500.0,"cost_ngn":15000.0,"time_min":50.0},
    {"id":"minibus","capacity_kg":500.0,"cost_ngn":8000.0,"time_min":50.0},
]
HOLDING_COST_NGN_KG_DAY=150.0
SHORTAGE_PENALTY_NGN_KG=7500.0
EMCV_CAPACITY_M3=1.0

HTC_STATES={
    "insulated":{"flow_m3_h":1.69,"reported_temperature_c":200.0,"reported_time_h":2.6,
                 "classification":"reported HTC target attainment"},
    "bare":{"flow_m3_h":3.00,"reported_temperature_c":180.0,"reported_time_h":None,
            "classification":"reported HTC-window attainment"},
    "bare_comparison":{"flow_m3_h":1.69,"reported_temperature_c":194.0,"reported_time_h":None,
            "classification":"reported comparison state; window not maintained"},
}

MODES=("htc_priority","electricity_priority","balanced")

def optimize_logistics(demand_kg, initial_inventory_kg=0.0, holding_days=1.0,
                       time_value_ngn_min=0.0, max_trips_per_vehicle=8):
    vals=[demand_kg,initial_inventory_kg,holding_days,time_value_ngn_min]
    if any(v<0 for v in vals): raise ValueError("Logistics inputs must be non-negative.")
    best=None
    for trips in product(range(max_trips_per_vehicle+1), repeat=len(VEHICLES)):
        delivered=sum(n*v["capacity_kg"] for n,v in zip(trips,VEHICLES))
        available=initial_inventory_kg+delivered
        shortage=max(0.0,demand_kg-available)
        ending=max(0.0,available-demand_kg)
        transport=sum(n*v["cost_ngn"] for n,v in zip(trips,VEHICLES))
        holding=ending*HOLDING_COST_NGN_KG_DAY*holding_days
        shortage_cost=shortage*SHORTAGE_PENALTY_NGN_KG
        cumulative_time=sum(n*v["time_min"] for n,v in zip(trips,VEHICLES))
        objective=transport+holding+shortage_cost+time_value_ngn_min*cumulative_time
        row=(objective,shortage,transport+holding+shortage_cost,cumulative_time,trips,
             delivered,ending,transport,holding,shortage_cost)
        if best is None or row[:4] < best[:4]: best=row
    obj,shortage,total,cum_time,trips,delivered,ending,transport,holding,shortage_cost=best
    return {
        "plan":{v["id"]:n for n,v in zip(trips,VEHICLES) if n},
        "delivered_kg":delivered,"ending_inventory_kg":ending,"shortage_kg":shortage,
        "transport_cost_ngn":transport,"holding_cost_ngn":holding,
        "shortage_cost_ngn":shortage_cost,"base_total_cost_ngn":total,
        "cumulative_trip_time_min":cum_time,"objective_ngn_equiv":obj
    }

def select_htc_state(configuration, require_htc_window=True):
    if configuration=="insulated": key="insulated"
    elif configuration=="bare": key="bare" if require_htc_window else "bare_comparison"
    else: raise ValueError("HTC configuration must be 'insulated' or 'bare'.")
    return {"state_id":key,"configuration":configuration,**HTC_STATES[key]}

def allocate_single_period(available_m3, htc_demand_m3, electricity_demand_m3,
                           reserve_min_m3, mode="balanced"):
    vals=[available_m3,htc_demand_m3,electricity_demand_m3,reserve_min_m3]
    if any(v<0 for v in vals): raise ValueError("Gas inputs must be non-negative.")
    if mode not in MODES: raise ValueError("Unsupported mode.")
    # Reserve is terminal inventory, not a consuming end-use.
    protected_reserve=min(available_m3,reserve_min_m3)
    usable=max(0.0,available_m3-protected_reserve)
    h=e=0.0
    if mode=="htc_priority":
        h=min(htc_demand_m3,usable); usable-=h
        e=min(electricity_demand_m3,usable); usable-=e
    elif mode=="electricity_priority":
        e=min(electricity_demand_m3,usable); usable-=e
        h=min(htc_demand_m3,usable); usable-=h
    else:
        total_demand=htc_demand_m3+electricity_demand_m3
        frac=0.0 if total_demand==0 else min(1.0,usable/total_demand)
        h=htc_demand_m3*frac; e=electricity_demand_m3*frac
        usable-=h+e
    terminal=protected_reserve+usable
    unmet={"htc":max(0.0,htc_demand_m3-h),
           "electricity":max(0.0,electricity_demand_m3-e),
           "reserve":max(0.0,reserve_min_m3-terminal)}
    return {
        "allocation_m3":{"htc":h,"electricity":e},
        "terminal_inventory_m3":terminal,
        "unmet_m3":unmet,
        "unused_above_minimum_reserve_m3":usable,
        "all_requirements_met":sum(unmet.values())<1e-10,
        "feasibility_threshold_m3":htc_demand_m3+electricity_demand_m3+reserve_min_m3
    }

def simulate_horizon(initial_inventory_m3, production_m3, htc_demand_m3,
                     electricity_demand_m3, reserve_min_m3, capacity_m3=EMCV_CAPACITY_M3,
                     mode="balanced"):
    arrays=[production_m3,htc_demand_m3,electricity_demand_m3,reserve_min_m3]
    n=len(production_m3)
    if not all(len(x)==n for x in arrays): raise ValueError("Horizon vectors must have equal length.")
    if any(v<0 for arr in arrays for v in arr) or initial_inventory_m3<0 or capacity_m3<=0:
        raise ValueError("Horizon values must be non-negative and capacity positive.")
    if initial_inventory_m3>capacity_m3: raise ValueError("Initial inventory exceeds capacity.")
    inv=initial_inventory_m3; periods=[]; total_overflow=0.0; max_err=0.0
    for t in range(n):
        gross=inv+production_m3[t]
        overflow=max(0.0,gross-capacity_m3)
        stored_available=min(gross,capacity_m3)
        a=allocate_single_period(stored_available,htc_demand_m3[t],
                                 electricity_demand_m3[t],reserve_min_m3[t],mode)
        end=a["terminal_inventory_m3"]
        # gross = overflow + HTC + electricity + end_inventory
        err=gross-(overflow+a["allocation_m3"]["htc"]+a["allocation_m3"]["electricity"]+end)
        max_err=max(max_err,abs(err)); total_overflow+=overflow
        periods.append({"period":t+1,"start_inventory_m3":inv,"production_m3":production_m3[t],
            "gross_resource_m3":gross,"overflow_or_unstored_m3":overflow,
            "stored_available_m3":stored_available,**a,"end_inventory_m3":end,
            "mass_balance_error_m3":err})
        inv=end
    return {"mode":mode,"capacity_m3":capacity_m3,"periods":periods,
            "final_inventory_m3":inv,"total_overflow_or_unstored_m3":total_overflow,
            "max_abs_mass_balance_error_m3":max_err}

def recommend(payload):
    logistics=optimize_logistics(payload["feedstock_demand_kg"],
        payload.get("initial_feedstock_inventory_kg",0.0),
        payload.get("holding_days",1.0),payload.get("time_value_ngn_min",0.0))
    htc=select_htc_state(payload.get("htc_configuration","insulated"),
                         payload.get("require_htc_window",True))
    gas=allocate_single_period(payload["available_gas_m3"],payload["htc_demand_m3"],
        payload["electricity_demand_m3"],payload["reserve_min_m3"],
        payload.get("operator_mode","balanced"))
    return {"status":"optimal","logistics":logistics,"htc":htc,"biogas":gas,
      "provenance":{"vehicle_parameters":"manuscript-reported",
       "holding_shortage_parameters":"manuscript-reported",
       "htc_states":"manuscript-reported discrete states",
       "EMCV_capacity":"manuscript-reported when 1.0 m3",
       "gas_demands":"runtime/upstream-model inputs",
       "reserve_minimum":"operator constraint","operator_mode":"DSS policy"}}
