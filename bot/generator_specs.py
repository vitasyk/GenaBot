from pydantic import BaseModel

class GeneratorSpec(BaseModel):
    name: str
    tank_capacity: float  # Liters
    consumption_rate: float  # Liters per hour

# Define specs for each generator (Initial default values)
GENERATOR_SPECS = {
    "GEN-1 (003)": GeneratorSpec(
        name="GEN-1 (003)",
        tank_capacity=40.0,
        consumption_rate=2.0
    ),
    "GEN-2 (036) WILSON": GeneratorSpec(
        name="GEN-2 (036) WILSON",
        tank_capacity=40.0,
        consumption_rate=2.0
    )
}
