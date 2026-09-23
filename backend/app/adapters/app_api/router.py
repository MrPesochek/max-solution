from fastapi import APIRouter

from app.adapters.app_api.routers import (
    attachments,
    auth,
    complaints,
    directories,
    equipment,
    integration,
    invitations,
    locations,
    marketplace,
    memberships,
    organizations,
    provider_profile,
    providers,
    requests,
    reviews,
    service_binding_invitations,
    service_bindings,
    showcase,
    verification,
)
from app.modules.identity import api as identity

API_PREFIX = "/app-api/v1"


def build_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(auth.router)
    router.include_router(showcase.router)
    if identity.demo_login_enabled():
        router.include_router(auth.demo_router)
    router.include_router(organizations.router)
    router.include_router(directories.router)
    router.include_router(locations.router)
    router.include_router(equipment.router)
    router.include_router(memberships.router)
    router.include_router(invitations.router)
    router.include_router(integration.router)
    router.include_router(provider_profile.router)
    router.include_router(providers.router)
    router.include_router(service_bindings.router)
    router.include_router(service_binding_invitations.router)
    router.include_router(verification.router)
    router.include_router(requests.router)
    router.include_router(marketplace.router)
    router.include_router(marketplace.offers_router)
    router.include_router(attachments.router)
    router.include_router(reviews.router)
    router.include_router(reviews.reviews_router)
    router.include_router(complaints.router)
    return router
