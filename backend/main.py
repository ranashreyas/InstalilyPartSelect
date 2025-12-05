from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import create_engine, text
import os

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin123@localhost:5432/searchdb")
engine = create_engine(DATABASE_URL)

app = FastAPI(
    title="PartSelect Parts API",
    description="API to query appliance parts and models from PartSelect data",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Pydantic Models
# =============================================================================

class ModelResponse(BaseModel):
    model_number: str
    name: Optional[str] = None
    brand: Optional[str] = None
    appliance_type: Optional[str] = None
    source_url: Optional[str] = None


class PartResponse(BaseModel):
    part_number: str
    manufacturer_part_number: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    manufacturer: Optional[str] = None
    appliance_type: Optional[str] = None
    source_url: Optional[str] = None


class ModelsListResponse(BaseModel):
    count: int
    filters: dict
    models: List[ModelResponse]


class PartsListResponse(BaseModel):
    count: int
    filters: dict
    parts: List[PartResponse]


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
def root():
    """Health check and API info endpoint."""
    return {
        "status": "running",
        "service": "PartSelect Parts API",
        "endpoints": {
            "list_models": "/models?appliance_type=&model_number=&brand=&name=",
            "list_parts": "/parts?appliance_type=&model_number=&manufacturer=&name=",
            "health": "/health"
        }
    }


@app.get("/health")
def health_check():
    """Check health of database connection."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/models", response_model=ModelsListResponse)
def list_models(
    appliance_type: Optional[str] = Query(None, description="Filter by appliance type (e.g., 'Refrigerator', 'Dishwasher')"),
    model_number: Optional[str] = Query(None, description="Filter by model number (exact or partial match)"),
    brand: Optional[str] = Query(None, description="Filter by brand (e.g., 'Bosch', 'Midea')"),
    name: Optional[str] = Query(None, description="Filter by name (partial match)")
):
    """
    List all models with optional filters.
    
    All filters support partial matching (case-insensitive).
    """
    try:
        # Build dynamic query
        query = "SELECT * FROM models WHERE 1=1"
        params = {}
        
        if appliance_type:
            query += " AND LOWER(appliance_type) LIKE LOWER(:appliance_type)"
            params["appliance_type"] = f"%{appliance_type}%"
        
        if model_number:
            query += " AND LOWER(model_number) LIKE LOWER(:model_number)"
            params["model_number"] = f"%{model_number}%"
        
        if brand:
            query += " AND LOWER(brand) LIKE LOWER(:brand)"
            params["brand"] = f"%{brand}%"
        
        if name:
            query += " AND LOWER(name) LIKE LOWER(:name)"
            params["name"] = f"%{name}%"
        
        query += " ORDER BY model_number"
        
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.fetchall()
            columns = result.keys()
        
        models = [dict(zip(columns, row)) for row in rows]
        
        return ModelsListResponse(
            count=len(models),
            filters={
                "appliance_type": appliance_type,
                "model_number": model_number,
                "brand": brand,
                "name": name
            },
            models=[ModelResponse(**m) for m in models]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/parts", response_model=PartsListResponse)
def list_parts(
    appliance_type: Optional[str] = Query(None, description="Filter by appliance type (e.g., 'Refrigerator', 'Dishwasher')"),
    name: Optional[str] = Query(None, description="Fuzzy search by part name or description - searches each word separately")
):
    """
    List/search parts with fuzzy name matching.
    
    The name search is fuzzy:
    - Searches both name AND description fields
    - Each word in the search is matched separately (OR logic)
    - Case-insensitive
    
    For model-specific parts, use /models/{model_number}/parts instead.
    For brand-specific parts, use /parts/by-appliance-brand instead.
    """
    try:
        params = {}
        query = "SELECT * FROM parts WHERE 1=1"
        
        if appliance_type:
            query += " AND LOWER(appliance_type) LIKE LOWER(:appliance_type)"
            params["appliance_type"] = f"%{appliance_type}%"
        
        if name:
            # Fuzzy search: split into words and match ANY word in name OR description
            words = name.strip().split()
            if words:
                word_conditions = []
                for i, word in enumerate(words):
                    param_name = f"word_{i}"
                    # Match word in name or description
                    word_conditions.append(
                        f"(LOWER(name) LIKE LOWER(:{param_name}) OR LOWER(COALESCE(description, '')) LIKE LOWER(:{param_name}))"
                    )
                    params[param_name] = f"%{word}%"
                
                # Use OR to match any word (fuzzy), not AND (strict)
                query += f" AND ({' OR '.join(word_conditions)})"
        
        query += " ORDER BY name"
        
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.fetchall()
            columns = result.keys()
        
        parts = [dict(zip(columns, row)) for row in rows]
        
        return PartsListResponse(
            count=len(parts),
            filters={
                "appliance_type": appliance_type,
                "name": name
            },
            parts=[PartResponse(**p) for p in parts]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models/{model_number}", response_model=ModelResponse)
def get_model(model_number: str):
    """Get a specific model by its model number."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM models WHERE model_number = :model_number"),
                {"model_number": model_number}
            )
            row = result.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Model '{model_number}' not found")
            
            columns = result.keys()
            model = dict(zip(columns, row))
            return ModelResponse(**model)
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/parts/{part_number}", response_model=PartResponse)
def get_part(part_number: str):
    """Get a specific part by its PartSelect number."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM parts WHERE part_number = :part_number"),
                {"part_number": part_number}
            )
            row = result.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Part '{part_number}' not found")
            
            columns = result.keys()
            part = dict(zip(columns, row))
            return PartResponse(**part)
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models/{model_number}/parts", response_model=PartsListResponse)
def get_model_parts(model_number: str):
    """Get all parts for a specific model using the junction table."""
    try:
        # First check if model exists
        with engine.connect() as conn:
            model_check = conn.execute(
                text("SELECT model_number FROM models WHERE model_number = :model_number"),
                {"model_number": model_number}
            )
            if not model_check.fetchone():
                raise HTTPException(status_code=404, detail=f"Model '{model_number}' not found")
            
            # Get parts for this model via junction table
            result = conn.execute(
                text("""
                    SELECT p.* FROM parts p
                    JOIN model_parts mp ON p.part_number = mp.part_number
                    WHERE mp.model_number = :model_number
                    ORDER BY p.part_number
                """),
                {"model_number": model_number}
            )
            rows = result.fetchall()
            columns = result.keys()
        
        parts = [dict(zip(columns, row)) for row in rows]
        
        return PartsListResponse(
            count=len(parts),
            filters={"model_number": model_number},
            parts=[PartResponse(**p) for p in parts]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/brands")
def get_brands():
    """Get all unique brands/manufacturers from both models and parts tables."""
    try:
        with engine.connect() as conn:
            # Get unique brands from models table
            model_brands = conn.execute(text(
                "SELECT DISTINCT brand FROM models WHERE brand IS NOT NULL ORDER BY brand"
            ))
            brands_from_models = [row[0] for row in model_brands]
            
            # Get unique manufacturers from parts table
            part_manufacturers = conn.execute(text(
                "SELECT DISTINCT manufacturer FROM parts WHERE manufacturer IS NOT NULL ORDER BY manufacturer"
            ))
            manufacturers_from_parts = [row[0] for row in part_manufacturers]
            
            # Combine and deduplicate
            all_brands = sorted(set(brands_from_models + manufacturers_from_parts))
        
        return {
            "count": len(all_brands),
            "brands": all_brands,
            "details": {
                "from_models": brands_from_models,
                "from_parts": manufacturers_from_parts
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/manufacturers")
def get_manufacturers():
    """Get all unique manufacturers from parts table with part counts."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT manufacturer, COUNT(*) as part_count 
                FROM parts 
                WHERE manufacturer IS NOT NULL 
                GROUP BY manufacturer 
                ORDER BY part_count DESC
            """))
            manufacturers = [{"manufacturer": row[0], "part_count": row[1]} for row in result]
        
        return {
            "count": len(manufacturers),
            "manufacturers": manufacturers
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/parts/by-price", response_model=PartsListResponse)
def search_parts_by_price(
    min_price: Optional[float] = Query(None, description="Minimum price"),
    max_price: Optional[float] = Query(None, description="Maximum price"),
    appliance_type: Optional[str] = Query(None, description="Filter by appliance type"),
    name: Optional[str] = Query(None, description="Filter by part name")
):
    """Search for parts within a price range."""
    try:
        query = "SELECT * FROM parts WHERE price IS NOT NULL"
        params = {}
        
        if min_price is not None:
            query += " AND price >= :min_price"
            params["min_price"] = min_price
        
        if max_price is not None:
            query += " AND price <= :max_price"
            params["max_price"] = max_price
        
        if appliance_type:
            query += " AND LOWER(appliance_type) LIKE LOWER(:appliance_type)"
            params["appliance_type"] = f"%{appliance_type}%"
        
        if name:
            query += " AND LOWER(name) LIKE LOWER(:name)"
            params["name"] = f"%{name}%"
        
        query += " ORDER BY price ASC"
        
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.fetchall()
            columns = result.keys()
        
        parts = [dict(zip(columns, row)) for row in rows]
        
        return PartsListResponse(
            count=len(parts),
            filters={
                "min_price": min_price,
                "max_price": max_price,
                "appliance_type": appliance_type,
                "name": name
            },
            parts=[PartResponse(**p) for p in parts]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/parts/by-appliance-brand", response_model=PartsListResponse)
def get_parts_by_appliance_brand(
    brand: str = Query(..., description="Appliance brand (e.g., 'Bosch', 'Whirlpool', 'Samsung')"),
    appliance_type: Optional[str] = Query(None, description="Filter by appliance type (e.g., 'Refrigerator', 'Dishwasher')"),
    name: Optional[str] = Query(None, description="Filter by part name (partial match)")
):
    """
    Get all parts compatible with appliances of a specific brand.
    
    This joins models → model_parts → parts to find parts for appliance brands.
    For example: "Find all parts for Bosch dishwashers"
    """
    try:
        # Join through model_parts to find parts compatible with models of this brand
        query = """
            SELECT DISTINCT p.*
            FROM parts p
            INNER JOIN model_parts mp ON p.part_number = mp.part_number
            INNER JOIN models m ON mp.model_number = m.model_number
            WHERE LOWER(m.brand) LIKE LOWER(:brand)
        """
        params = {"brand": f"%{brand}%"}
        
        if appliance_type:
            query += " AND LOWER(m.appliance_type) LIKE LOWER(:appliance_type)"
            params["appliance_type"] = f"%{appliance_type}%"
        
        if name:
            query += " AND LOWER(p.name) LIKE LOWER(:name)"
            params["name"] = f"%{name}%"
        
        query += " ORDER BY p.name"
        
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.fetchall()
            columns = result.keys()
        
        parts = [dict(zip(columns, row)) for row in rows]
        
        return PartsListResponse(
            count=len(parts),
            filters={
                "brand": brand,
                "appliance_type": appliance_type,
                "name": name
            },
            parts=[PartResponse(**p) for p in parts]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/parts/{part_number}/models", response_model=ModelsListResponse)
def get_part_compatible_models(part_number: str):
    """Get all models that are compatible with a specific part using the junction table."""
    try:
        # First check if part exists
        with engine.connect() as conn:
            part_check = conn.execute(
                text("SELECT part_number FROM parts WHERE part_number = :part_number"),
                {"part_number": part_number}
            )
            if not part_check.fetchone():
                raise HTTPException(status_code=404, detail=f"Part '{part_number}' not found")
            
            # Get models for this part via junction table
            result = conn.execute(
                text("""
                    SELECT m.* FROM models m
                    JOIN model_parts mp ON m.model_number = mp.model_number
                    WHERE mp.part_number = :part_number
                    ORDER BY m.brand, m.model_number
                """),
                {"part_number": part_number}
            )
            rows = result.fetchall()
            columns = result.keys()
        
        models = [dict(zip(columns, row)) for row in rows]
        
        return ModelsListResponse(
            count=len(models),
            filters={"part_number": part_number},
            models=[ModelResponse(**m) for m in models]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/appliance-types")
def get_appliance_types():
    """Get all unique appliance types available in the database."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT DISTINCT appliance_type, COUNT(*) as model_count FROM models WHERE appliance_type IS NOT NULL GROUP BY appliance_type ORDER BY appliance_type"
            ))
            types = [{"appliance_type": row[0], "model_count": row[1]} for row in result]
        
        return {
            "count": len(types),
            "appliance_types": types
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
