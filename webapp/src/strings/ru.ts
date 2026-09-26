import { common, states, ui, header, money, attachments, errorCodes, actions } from './ru/common';
import { nav } from './ru/nav';
import { session, onboarding, orgForm, orgPicker, roles, orgKinds, invitationAccept } from './ru/onboarding';
import { locations, organization } from './ru/organization';
import { home, requests } from './ru/requests';
import { offers, approvals, requestsCard } from './ru/card';
import { equipment } from './ru/equipment';
import { bindings } from './ru/bindings';
import { provider, workspace } from './ru/provider';
import { integration } from './ru/integration';
import { reviews, complaints } from './ru/reviews';
import { operator } from './ru/operator';

export const strings = {
  common,
  states,
  session,
  onboarding,
  orgForm,
  orgPicker,
  roles,
  orgKinds,
  ui,
  nav,
  home,
  locations,
  equipment,
  organization,
  invitationAccept,
  header,
  provider,
  bindings,
  integration,
  money,
  requests: { ...requests, ...requestsCard },
  offers,
  reviews,
  complaints,
  approvals,
  workspace,
  operator,
  attachments,
  errorCodes,
  actions,
} as const;
