from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, List
from .engine import optimize_logistics, select_htc_state, allocate_single_period, simulate_horizon, recommend

app=FastAPI(title="EnerghxPLUS AD-HTC-EMCV Prescriptive DSS",version="2.0.0")

class RecommendRequest(BaseModel):
    feedstock_demand_kg: float=Field(ge=0)
    initial_feedstock_inventory_kg: float=Field(default=0,ge=0)
    holding_days: float=Field(default=1,ge=0)
    time_value_ngn_min: float=Field(default=0,ge=0)
    available_gas_m3: float=Field(ge=0)
    htc_demand_m3: float=Field(ge=0)
    electricity_demand_m3: float=Field(ge=0)
    reserve_min_m3: float=Field(ge=0)
    htc_configuration: Literal["insulated","bare"]="insulated"
    require_htc_window: bool=True
    operator_mode: Literal["htc_priority","electricity_priority","balanced"]="balanced"

class HorizonRequest(BaseModel):
    initial_inventory_m3: float=Field(default=0,ge=0)
    production_m3: List[float]
    htc_demand_m3: List[float]
    electricity_demand_m3: List[float]
    reserve_min_m3: List[float]
    capacity_m3: float=Field(default=1.0,gt=0)
    operator_mode: Literal["htc_priority","electricity_priority","balanced"]="balanced"

@app.get("/health")
def health(): return {"status":"ok","version":"2.0.0"}

@app.get("/dss/config")
def config():
    return {"operator_modes":["htc_priority","electricity_priority","balanced"],
            "htc_configurations":["insulated","bare"],"nominal_emcv_capacity_m3":1.0}

@app.post("/dss/recommend")
def integrated(req:RecommendRequest):
    try: return recommend(req.model_dump())
    except ValueError as e: raise HTTPException(422,str(e))

@app.post("/dss/logistics")
def logistics(feedstock_demand_kg:float,initial_inventory_kg:float=0,holding_days:float=1):
    return optimize_logistics(feedstock_demand_kg,initial_inventory_kg,holding_days)

@app.post("/dss/htc")
def htc(configuration:Literal["insulated","bare"],require_htc_window:bool=True):
    return select_htc_state(configuration,require_htc_window)

@app.post("/dss/biogas/single-period")
def gas_single(available_m3:float,htc_demand_m3:float,electricity_demand_m3:float,
               reserve_min_m3:float,mode:Literal["htc_priority","electricity_priority","balanced"]="balanced"):
    return allocate_single_period(available_m3,htc_demand_m3,electricity_demand_m3,reserve_min_m3,mode)

@app.post("/dss/biogas/horizon")
def gas_horizon(req:HorizonRequest):
    try:
        return simulate_horizon(req.initial_inventory_m3,req.production_m3,req.htc_demand_m3,
          req.electricity_demand_m3,req.reserve_min_m3,req.capacity_m3,req.operator_mode)
    except ValueError as e: raise HTTPException(422,str(e))
