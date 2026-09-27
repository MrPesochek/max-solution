import { lazy, Suspense } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { MainLayout } from './components/layout/MainLayout';
import { RequireOrganization } from './components/layout/RequireOrganization';
import { RequireOperator } from './components/layout/RequireOperator';
import { Skeleton } from './components/states/Skeleton';
import { LocationsListScreen } from './screens/locations/LocationsListScreen';
import { AcceptInvitationScreen } from './screens/invitations/AcceptInvitationScreen';
import { EquipmentLocationRedirect, EquipmentScreen } from './screens/equipment/EquipmentScreen';
import { HomeScreen } from './screens/home/HomeScreen';
import { RequestsScreen } from './screens/requests/RequestsScreen';
import { OnboardingScreen } from './screens/onboarding/OnboardingScreen';
import { OrganizationPickerScreen } from './screens/onboarding/OrganizationPickerScreen';

const NewRequestScreen = lazy(() =>
  import('./screens/requests/NewRequestScreen').then((m) => ({ default: m.NewRequestScreen })),
);
const RequestDetailScreen = lazy(() =>
  import('./screens/requests/RequestDetailScreen').then((m) => ({
    default: m.RequestDetailScreen,
  })),
);
const PublishSearchScreen = lazy(() =>
  import('./screens/requests/PublishSearchScreen').then((m) => ({
    default: m.PublishSearchScreen,
  })),
);
const UpdateDetailsScreen = lazy(() =>
  import('./screens/requests/UpdateDetailsScreen').then((m) => ({
    default: m.UpdateDetailsScreen,
  })),
);
const CancelRequestScreen = lazy(() =>
  import('./screens/requests/CancelRequestScreen').then((m) => ({
    default: m.CancelRequestScreen,
  })),
);
const OffersScreen = lazy(() =>
  import('./screens/offers/OffersScreen').then((m) => ({ default: m.OffersScreen })),
);
const OfferDetailScreen = lazy(() =>
  import('./screens/offers/OfferDetailScreen').then((m) => ({ default: m.OfferDetailScreen })),
);
const OfferQuestionScreen = lazy(() =>
  import('./screens/offers/OfferQuestionScreen').then((m) => ({ default: m.OfferQuestionScreen })),
);
const RequestMessagesScreen = lazy(() =>
  import('./screens/requests/card/RequestMessagesScreen').then((m) => ({
    default: m.RequestMessagesScreen,
  })),
);
const RequestHistoryScreen = lazy(() =>
  import('./screens/requests/card/RequestHistoryScreen').then((m) => ({
    default: m.RequestHistoryScreen,
  })),
);
const VisitApprovalScreen = lazy(() =>
  import('./screens/approvals/VisitApprovalScreen').then((m) => ({
    default: m.VisitApprovalScreen,
  })),
);
const RepairQuoteApprovalScreen = lazy(() =>
  import('./screens/approvals/RepairQuoteApprovalScreen').then((m) => ({
    default: m.RepairQuoteApprovalScreen,
  })),
);
const LocationFormScreen = lazy(() =>
  import('./screens/locations/LocationFormScreen').then((m) => ({ default: m.LocationFormScreen })),
);
const EquipmentFormScreen = lazy(() =>
  import('./screens/equipment/EquipmentFormScreen').then((m) => ({
    default: m.EquipmentFormScreen,
  })),
);
const EquipmentCardScreen = lazy(() =>
  import('./screens/equipment/EquipmentCardScreen').then((m) => ({
    default: m.EquipmentCardScreen,
  })),
);
const WarrantyScreen = lazy(() =>
  import('./screens/bindings/WarrantyScreen').then((m) => ({ default: m.WarrantyScreen })),
);
const OrganizationScreen = lazy(() =>
  import('./screens/organization/OrganizationScreen').then((m) => ({
    default: m.OrganizationScreen,
  })),
);
const StaffLocationsScreen = lazy(() =>
  import('./screens/organization/StaffLocationsScreen').then((m) => ({
    default: m.StaffLocationsScreen,
  })),
);
const StaffScreen = lazy(() =>
  import('./screens/organization/StaffScreen').then((m) => ({ default: m.StaffScreen })),
);
const NewInvitationScreen = lazy(() =>
  import('./screens/organization/NewInvitationScreen').then((m) => ({
    default: m.NewInvitationScreen,
  })),
);
const OrganizationProfileScreen = lazy(() =>
  import('./screens/organization/OrganizationProfileSection').then((m) => ({
    default: m.OrganizationProfileScreen,
  })),
);
const ParticipationScreen = lazy(() =>
  import('./screens/organization/ParticipationSection').then((m) => ({
    default: m.ParticipationScreen,
  })),
);
const CreateOrganizationScreen = lazy(() =>
  import('./screens/onboarding/CreateOrganizationScreen').then((m) => ({
    default: m.CreateOrganizationScreen,
  })),
);
const ProviderProfileScreen = lazy(() =>
  import('./screens/provider/ProviderProfileScreen').then((m) => ({
    default: m.ProviderProfileScreen,
  })),
);
const ProviderVerificationScreen = lazy(() =>
  import('./screens/provider/ProviderVerificationScreen').then((m) => ({
    default: m.ProviderVerificationScreen,
  })),
);

const IntegrationScreen = lazy(() =>
  import('./screens/integration/IntegrationScreen').then((m) => ({ default: m.IntegrationScreen })),
);
const ProviderPublicProfileScreen = lazy(() =>
  import('./screens/provider/ProviderPublicProfileScreen').then((m) => ({
    default: m.ProviderPublicProfileScreen,
  })),
);
const ProviderCatalogScreen = lazy(() =>
  import('./screens/provider/ProviderCatalogScreen').then((m) => ({
    default: m.ProviderCatalogScreen,
  })),
);
const BindingsListScreen = lazy(() =>
  import('./screens/bindings/BindingsListScreen').then((m) => ({ default: m.BindingsListScreen })),
);
const AddBindingScreen = lazy(() =>
  import('./screens/bindings/AddBindingScreen').then((m) => ({ default: m.AddBindingScreen })),
);
const BindingAcceptScreen = lazy(() =>
  import('./screens/bindings/BindingAcceptScreen').then((m) => ({
    default: m.BindingAcceptScreen,
  })),
);
const ProviderIncomingBindingsScreen = lazy(() =>
  import('./screens/bindings/ProviderIncomingBindingsScreen').then((m) => ({
    default: m.ProviderIncomingBindingsScreen,
  })),
);
const ProviderBindingInvitationsScreen = lazy(() =>
  import('./screens/bindings/ProviderBindingInvitationsScreen').then((m) => ({
    default: m.ProviderBindingInvitationsScreen,
  })),
);

const ProviderRequestsHubScreen = lazy(() =>
  import('./screens/provider/ProviderRequestsHubScreen').then((m) => ({
    default: m.ProviderRequestsHubScreen,
  })),
);
const ProviderChatsScreen = lazy(() =>
  import('./screens/provider/ProviderChatsScreen').then((m) => ({
    default: m.ProviderChatsScreen,
  })),
);
const ProviderIncomingScreen = lazy(() =>
  import('./screens/provider/ProviderIncomingScreen').then((m) => ({
    default: m.ProviderIncomingScreen,
  })),
);
const ProviderInWorkScreen = lazy(() =>
  import('./screens/provider/ProviderInWorkScreen').then((m) => ({
    default: m.ProviderInWorkScreen,
  })),
);
const ProviderAvailableScreen = lazy(() =>
  import('./screens/provider/ProviderAvailableScreen').then((m) => ({
    default: m.ProviderAvailableScreen,
  })),
);
const MarketplaceCardScreen = lazy(() =>
  import('./screens/provider/MarketplaceCardScreen').then((m) => ({
    default: m.MarketplaceCardScreen,
  })),
);
const ProviderRequestDetailScreen = lazy(() =>
  import('./screens/provider/ProviderRequestDetailScreen').then((m) => ({
    default: m.ProviderRequestDetailScreen,
  })),
);

const ProviderReviewsScreen = lazy(() =>
  import('./screens/provider/ProviderReviewsScreen').then((m) => ({
    default: m.ProviderReviewsScreen,
  })),
);
const MyComplaintsScreen = lazy(() =>
  import('./screens/reviews/MyComplaintsScreen').then((m) => ({ default: m.MyComplaintsScreen })),
);
const ProviderPublicReviewsScreen = lazy(() =>
  import('./screens/provider/ProviderReviewsScreen').then((m) => ({
    default: m.ProviderPublicReviewsScreen,
  })),
);
const RequestReviewScreen = lazy(() =>
  import('./screens/reviews/RequestReviewSection').then((m) => ({ default: m.RequestReviewScreen })),
);

const OperatorHomeScreen = lazy(() =>
  import('./screens/operator/OperatorHomeScreen').then((m) => ({ default: m.OperatorHomeScreen })),
);
const VerificationQueueScreen = lazy(() =>
  import('./screens/operator/VerificationQueueScreen').then((m) => ({
    default: m.VerificationQueueScreen,
  })),
);
const ProviderProfilesScreen = lazy(() =>
  import('./screens/operator/ProviderProfilesScreen').then((m) => ({
    default: m.ProviderProfilesScreen,
  })),
);
const WarrantyAuthorizationsScreen = lazy(() =>
  import('./screens/operator/WarrantyAuthorizationsScreen').then((m) => ({
    default: m.WarrantyAuthorizationsScreen,
  })),
);
const ServiceBindingsQueueScreen = lazy(() =>
  import('./screens/operator/ServiceBindingsQueueScreen').then((m) => ({
    default: m.ServiceBindingsQueueScreen,
  })),
);
const AttachmentModerationScreen = lazy(() =>
  import('./screens/operator/AttachmentModerationScreen').then((m) => ({
    default: m.AttachmentModerationScreen,
  })),
);
const ReviewsModerationScreen = lazy(() =>
  import('./screens/operator/ReviewsModerationScreen').then((m) => ({
    default: m.ReviewsModerationScreen,
  })),
);
const ComplaintsQueueScreen = lazy(() =>
  import('./screens/operator/ComplaintsQueueScreen').then((m) => ({
    default: m.ComplaintsQueueScreen,
  })),
);

const SHOWCASE_ENABLED = import.meta.env.DEV || import.meta.env.VITE_USE_MOCKS === 'true';
const Showcase = lazy(() => import('./ui/showcase/Showcase').then((m) => ({ default: m.Showcase })));

function LazyFallback() {
  return <Skeleton lines={4} />;
}

export function AppRouter() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/onboarding" element={<OnboardingScreen />} />
        <Route
          path="/onboarding/new-organization/:kind"
          element={
            <Suspense fallback={<LazyFallback />}>
              <CreateOrganizationScreen />
            </Suspense>
          }
        />
        <Route path="/showcase/operator" element={
          <div className="ui-layout"><Suspense fallback={<LazyFallback />}><VerificationQueueScreen demo /></Suspense></div>
        } />
        <Route path="/organizations" element={<OrganizationPickerScreen />} />
        <Route path="/invitations/accept" element={<AcceptInvitationScreen />} />
        {SHOWCASE_ENABLED && (
          <Route
            path="/__ui/:frame?"
            element={
              <Suspense fallback={<LazyFallback />}>
                <Showcase />
              </Suspense>
            }
          />
        )}

        <Route
          element={
            <RequireOrganization>
              <MainLayout />
            </RequireOrganization>
          }
        >
          <Route path="/" element={<HomeScreen />} />
          <Route path="/requests" element={<RequestsScreen />} />
          <Route
            path="/requests/new"
            element={
              <Suspense fallback={<LazyFallback />}>
                <NewRequestScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id"
            element={
              <Suspense fallback={<LazyFallback />}>
                <RequestDetailScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/publish"
            element={
              <Suspense fallback={<LazyFallback />}>
                <PublishSearchScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/details"
            element={
              <Suspense fallback={<LazyFallback />}>
                <UpdateDetailsScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/cancel"
            element={
              <Suspense fallback={<LazyFallback />}>
                <CancelRequestScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/review"
            element={
              <Suspense fallback={<LazyFallback />}>
                <RequestReviewScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/offers"
            element={
              <Suspense fallback={<LazyFallback />}>
                <OffersScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/offers/:offerId"
            element={
              <Suspense fallback={<LazyFallback />}>
                <OfferDetailScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/offers/:offerId/messages"
            element={
              <Suspense fallback={<LazyFallback />}>
                <OfferQuestionScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/questions/:providerId"
            element={
              <Suspense fallback={<LazyFallback />}>
                <OfferQuestionScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/messages"
            element={
              <Suspense fallback={<LazyFallback />}>
                <RequestMessagesScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/history"
            element={
              <Suspense fallback={<LazyFallback />}>
                <RequestHistoryScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/visit-proposals/:proposalId"
            element={
              <Suspense fallback={<LazyFallback />}>
                <VisitApprovalScreen />
              </Suspense>
            }
          />
          <Route
            path="/requests/:id/repair-quotes/:quoteId"
            element={
              <Suspense fallback={<LazyFallback />}>
                <RepairQuoteApprovalScreen />
              </Suspense>
            }
          />
          <Route path="/locations" element={<LocationsListScreen />} />
          <Route
            path="/locations/new"
            element={
              <Suspense fallback={<LazyFallback />}>
                <LocationFormScreen />
              </Suspense>
            }
          />
          <Route
            path="/locations/:id"
            element={
              <Suspense fallback={<LazyFallback />}>
                <LocationFormScreen />
              </Suspense>
            }
          />
          <Route path="/equipment" element={<EquipmentScreen />} />
          <Route
            path="/equipment/new"
            element={
              <Suspense fallback={<LazyFallback />}>
                <EquipmentFormScreen />
              </Suspense>
            }
          />
          <Route path="/equipment/:locationId" element={<EquipmentLocationRedirect />} />
          <Route
            path="/equipment/:locationId/new"
            element={
              <Suspense fallback={<LazyFallback />}>
                <EquipmentFormScreen />
              </Suspense>
            }
          />
          <Route
            path="/equipment/:locationId/:equipmentId"
            element={
              <Suspense fallback={<LazyFallback />}>
                <EquipmentCardScreen />
              </Suspense>
            }
          />
          <Route
            path="/equipment/:locationId/:equipmentId/warranty"
            element={
              <Suspense fallback={<LazyFallback />}>
                <WarrantyScreen />
              </Suspense>
            }
          />
          <Route
            path="/organization"
            element={
              <Suspense fallback={<LazyFallback />}>
                <OrganizationScreen />
              </Suspense>
            }
          />
          <Route
            path="/organization/staff"
            element={
              <Suspense fallback={<LazyFallback />}>
                <StaffScreen />
              </Suspense>
            }
          />
          <Route
            path="/organization/invite"
            element={
              <Suspense fallback={<LazyFallback />}>
                <NewInvitationScreen />
              </Suspense>
            }
          />
          <Route
            path="/organization/profile"
            element={
              <Suspense fallback={<LazyFallback />}>
                <OrganizationProfileScreen />
              </Suspense>
            }
          />
          <Route
            path="/organization/participation"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ParticipationScreen />
              </Suspense>
            }
          />
          <Route
            path="/organization/staff/:membershipId/locations"
            element={
              <Suspense fallback={<LazyFallback />}>
                <StaffLocationsScreen />
              </Suspense>
            }
          />

          <Route
            path="/providers"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderCatalogScreen />
              </Suspense>
            }
          />
          <Route
            path="/providers/:providerId"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderPublicProfileScreen />
              </Suspense>
            }
          />

          <Route
            path="/providers/:providerId/reviews"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderPublicReviewsScreen />
              </Suspense>
            }
          />

          <Route
            path="/complaints"
            element={
              <Suspense fallback={<LazyFallback />}>
                <MyComplaintsScreen />
              </Suspense>
            }
          />

          <Route
            path="/bindings"
            element={
              <Suspense fallback={<LazyFallback />}>
                <BindingsListScreen />
              </Suspense>
            }
          />
          <Route
            path="/bindings/new"
            element={
              <Suspense fallback={<LazyFallback />}>
                <AddBindingScreen />
              </Suspense>
            }
          />
          <Route
            path="/bindings/accept"
            element={
              <Suspense fallback={<LazyFallback />}>
                <BindingAcceptScreen />
              </Suspense>
            }
          />
          <Route
            path="/bindings/incoming"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderIncomingBindingsScreen />
              </Suspense>
            }
          />
          <Route
            path="/bindings/invitations"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderBindingInvitationsScreen />
              </Suspense>
            }
          />

          <Route
            path="/provider/profile"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderProfileScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/profile/:section"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderProfileScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/verification"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderVerificationScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/reviews"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderReviewsScreen />
              </Suspense>
            }
          />
          <Route
            path="/integration"
            element={
              <Suspense fallback={<LazyFallback />}>
                <IntegrationScreen />
              </Suspense>
            }
          />
          <Route
            path="/integration/:section"
            element={
              <Suspense fallback={<LazyFallback />}>
                <IntegrationScreen />
              </Suspense>
            }
          />

          <Route
            path="/provider/requests"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderRequestsHubScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/chats"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderChatsScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/incoming"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderIncomingScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/available"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderAvailableScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/available/:id"
            element={
              <Suspense fallback={<LazyFallback />}>
                <MarketplaceCardScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/in-work"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderInWorkScreen />
              </Suspense>
            }
          />
          <Route
            path="/provider/requests/:id"
            element={
              <Suspense fallback={<LazyFallback />}>
                <ProviderRequestDetailScreen />
              </Suspense>
            }
          />

          <Route
            path="/operator"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <OperatorHomeScreen />
                </Suspense>
              </RequireOperator>
            }
          />
          <Route
            path="/operator/verification"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <VerificationQueueScreen />
                </Suspense>
              </RequireOperator>
            }
          />
          <Route
            path="/operator/providers"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <ProviderProfilesScreen />
                </Suspense>
              </RequireOperator>
            }
          />
          <Route
            path="/operator/warranty"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <WarrantyAuthorizationsScreen />
                </Suspense>
              </RequireOperator>
            }
          />
          <Route
            path="/operator/bindings"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <ServiceBindingsQueueScreen />
                </Suspense>
              </RequireOperator>
            }
          />
          <Route
            path="/operator/attachments"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <AttachmentModerationScreen />
                </Suspense>
              </RequireOperator>
            }
          />
          <Route
            path="/operator/reviews"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <ReviewsModerationScreen />
                </Suspense>
              </RequireOperator>
            }
          />
          <Route
            path="/operator/complaints"
            element={
              <RequireOperator>
                <Suspense fallback={<LazyFallback />}>
                  <ComplaintsQueueScreen />
                </Suspense>
              </RequireOperator>
            }
          />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}
