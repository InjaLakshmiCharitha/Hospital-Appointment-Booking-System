from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Department, Doctor
from app.schemas.department import (
    DepartmentCreate,
    DepartmentUpdate,
    DepartmentResponse,
)
from app.auth.dependencies import require_roles
from typing import Optional

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.get("")
def list_departments(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(
        None,
        min_length=1,
        max_length=100,
    ),
    db: Session = Depends(get_db),
):
    query = db.query(Department)

    if search is not None:
        search_term = search.strip()

        if not search_term:
            raise HTTPException(
                status_code=422,
                detail="Search text cannot be empty",
            )

        query = query.filter(
            Department.name.ilike(f"%{search_term}%")
        )

    query = query.order_by(
        Department.name,
        Department.id,
    )

    offset = (page - 1) * page_size

    return query.offset(offset).limit(page_size).all()


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(department_id: int, db: Session = Depends(get_db)):
    department = db.query(Department).filter(
        Department.id == department_id,
        Department.is_active.is_(True),
    ).first()

    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")

    return department


@router.post(
    "/",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_department(
    data: DepartmentCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_roles("admin")),
):
    name = data.name.strip()

    if not name:
        raise HTTPException(status_code=422, detail="Department name is required")

    existing = db.query(Department).filter(
        Department.name.ilike(name)
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="A department with this name already exists",
        )

    department = Department(
        name=name,
        description=data.description,
        is_active=True,
    )

    db.add(department)
    try:
        db.commit()
        db.refresh(department)
    except Exception:
        db.rollback()
        raise

    return department


@router.put("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    data: DepartmentUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_roles("admin")),
):
    department = db.query(Department).filter(
        Department.id == department_id
    ).first()

    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")

    changes = data.model_dump(exclude_unset=True)

    if "name" in changes and changes["name"] is not None:
        name = changes["name"].strip()
        if not name:
            raise HTTPException(status_code=422, detail="Department name is required")

        duplicate = db.query(Department).filter(
            Department.name.ilike(name),
            Department.id != department_id,
        ).first()

        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="A department with this name already exists",
            )

        changes["name"] = name

    if changes.get("is_active") is False:
        active_doctor = db.query(Doctor).filter(
            Doctor.department_id == department_id,
            Doctor.is_active.is_(True),
        ).first()

        if active_doctor:
            raise HTTPException(
                status_code=409,
                detail="Deactivate or move active doctors before deactivating this department",
            )

    for field, value in changes.items():
        setattr(department, field, value)

    try:
        db.commit()
        db.refresh(department)
    except Exception:
        db.rollback()
        raise

    return department


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    department_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_roles("admin")),
):
    department = db.query(Department).filter(
        Department.id == department_id
    ).first()

    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")

    active_doctor = db.query(Doctor).filter(
        Doctor.department_id == department_id,
        Doctor.is_active.is_(True),
    ).first()

    if active_doctor:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a department that has active doctors",
        )

    # Keep the department record to preserve historical references.
    department.is_active = False

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return None