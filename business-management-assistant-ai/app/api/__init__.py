from app.api import approvals, records, system

routers = (system.router, records.router, approvals.router)
