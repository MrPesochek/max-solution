import { useState, type ReactNode } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { ErrorState } from '../../components/states/ErrorState';
import { useActiveRequests, useRequestMessages } from '../../api/hooks/useRequests';
import { useLocations } from '../../api/hooks/useLocations';
import { useOrgEquipment } from '../../api/hooks/useEquipment';
import { useProvidersCount } from '../../api/hooks/useProviders';
import { usePendingApprovals, type ApprovalItem } from '../../api/hooks/useApprovals';
import { useSession } from '../../session/SessionContext';
import { canManageRequestApprovals, isProvider } from '../../lib/roles';
import type { Equipment, RequestListItem } from '../../api/types';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { useLayout } from '../../ui/layout/layoutContext';
import { SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { SegmentTabs } from '../../ui/Segmented';
import { SceneBanner } from '../../ui/SceneBanner';
import { Sheet } from '../../ui/Sheet';
import { SkeletonRows } from '../../ui/Skeleton';
import { EquipmentIcon } from '../../ui/EquipmentIcon';
import { equipmentIllustration } from '../../ui/illustrations';
import { initials, relativeDay } from '../../ui/format';
import { ChevronDownIcon, ChevronRightIcon, PlusIcon } from '../../ui/icons';
import { equipmentTitle, listItemEquipmentName } from '../requests/components/equipmentName';
import { listStatus } from '../requests/components/listStatus';
import { equipmentLine } from '../equipment/equipmentView';
import { decisionSubtitle } from './decisionText';
import './home.css';

const t = strings.home;
type Tab = 'my' | 'find';
const EQUIPMENT_PREVIEW = 2;

function HomeCard({
  to,
  title,
  categoryName,
  status,
  accent,
  details,
  fill,
}: {
  to: string;
  title: string;
  categoryName?: string | null;
  status: ReactNode;
  accent?: boolean;
  details?: ReactNode;
  fill?: boolean;
}) {
  return (
    <Link className={`home-card${fill ? ' home-card--fill' : ''}`} to={to}>
      <EquipmentIcon name={categoryName ?? title} width={64} />
      <span className="home-card__main">
        <span className="home-card__title">{title}</span>
        <span className={`home-card__status${accent ? ' home-card__status--accent' : ''}`}>{status}</span>
        {details && <span className="home-card__details">{details}</span>}
      </span>
      <span className="home-card__chevron">
        <ChevronRightIcon />
      </span>
    </Link>
  );
}

function QuestionCard({ approval, item }: { approval: ApprovalItem; item: RequestListItem | undefined }) {
  const messages = useRequestMessages(approval.requestId, Boolean(approval.messageId), { poll: false });
  const text = messages.data?.find((m) => m.id === approval.messageId)?.body?.trim();
  return (
    <HomeCard
      to={approval.href}
      title={item ? listItemEquipmentName(item) : strings.ui.requestTitle(approval.requestNumber)}
      categoryName={item?.equipment_category_name}
      status={t.approvalTag.question}
      accent
      details={text || t.questionFallback}
      fill
    />
  );
}

function equipmentSubtitle(item: Equipment): string {
  return equipmentLine(item).text;
}

export function HomeScreen() {
  const { activeMembership, user } = useSession();
  const layout = useLayout();
  const active = useActiveRequests();
  const approvals = usePendingApprovals();
  const locations = useLocations();
  const equipment = useOrgEquipment();
  const [tab, setTab] = useState<Tab>('my');
  const [pointId, setPointId] = useState('');
  const [pointsOpen, setPointsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const isManager = activeMembership ? canManageRequestApprovals(activeMembership.role) : false;
  const own = new Set(activeMembership?.location_ids ?? []);
  const points = (locations.data ?? []).filter((l) => isManager || own.size === 0 || own.has(l.id));
  const single = points.length === 1 ? points[0]! : null;
  const point = single ?? points.find((l) => l.id === pointId) ?? null;
  const providers = useProvidersCount(
    { cityId: point?.city_id, districtId: point?.district_id ?? undefined },
    Boolean(point) && tab === 'find',
  );

  if (!activeMembership) return null;
  if (isProvider(activeMembership.role)) return <Navigate to="/provider/incoming" replace />;

  const inPoint = (locationId: string | null | undefined, locationName?: string | null) =>
    !point || locationId === point.id || (!locationId && locationName === point.name);

  const items = (active.data ?? []).filter((item) => inPoint(item.location_id, item.location_name));
  const byId = new Map((active.data ?? []).map((item) => [item.id, item]));
  const approvalInPoint = (a: ApprovalItem) => {
    const item = byId.get(a.requestId);
    return !item || inPoint(item.location_id, item.location_name);
  };

  const questions = approvals.approvals.filter((a) => a.kind === 'question' && approvalInPoint(a));
  const decisions = isManager
    ? approvals.approvals.filter((a) => a.kind !== 'question' && approvalInPoint(a))
    : [];
  const decisionIds = new Set([...decisions, ...questions].map((a) => a.requestId));
  const drafts = items.filter((item) => item.status === 'draft');
  const working = items.filter((item) => item.status !== 'draft' && !decisionIds.has(item.id));
  const searching = items.filter((item) => item.status === 'searching');

  const pointEquipment = (equipment.data ?? []).filter((e) => inPoint(e.location_id));
  const loading = active.isPending || approvals.isLoading;
  const failed = [active, locations, equipment].find((q) => q.isError);
  const loadError = failed?.error ?? (approvals.isError ? approvals.error : null);
  const hasError = Boolean(failed) || approvals.isError;
  const retryAll = () => {
    if (active.isError) void active.refetch();
    if (approvals.isError) void approvals.refetch();
    if (locations.isError) void locations.refetch();
    if (equipment.isError) void equipment.refetch();
  };
  const nothing =
    active.isSuccess &&
    !loading &&
    !hasError &&
    decisions.length === 0 &&
    questions.length === 0 &&
    items.length === 0;

  const organizationName = layout.activeContext?.organization ?? activeMembership.organization.name;
  const pointName = point?.name ?? (points.length > 1 ? t.allPoints : null);
  const pointHeader = pointName && (
    <>
      <span className="home-point__label">{t.pointLabel}</span>
      <span className="home-point__name">
        <span className="home-point__text">{pointName}</span>
        {points.length > 1 && <ChevronDownIcon />}
      </span>
    </>
  );

  const decisionsBlock = !loading && (
    <>
      {questions.length > 0 && (
        <section className="home-section" aria-labelledby="home-questions">
          <SectionCaption id="home-questions" large>
            {t.needAnswer}
          </SectionCaption>
          <div className="home-cards">
            {questions.map((approval) => (
              <QuestionCard key={approval.key} approval={approval} item={byId.get(approval.requestId)} />
            ))}
          </div>
        </section>
      )}

      {decisions.length > 0 && (
        <section className="home-section" aria-labelledby="home-decisions">
          <SectionCaption id="home-decisions" large>
            {t.needDecision}
          </SectionCaption>
          <div className="home-cards">
            {decisions.map((approval) => {
              const item = byId.get(approval.requestId);
              const decision =
                approval.decision ??
                (item?.pending_decision?.kind === approval.kind ? item.pending_decision : null);
              return (
                <HomeCard
                  key={approval.key}
                  to={approval.href}
                  title={item ? listItemEquipmentName(item) : strings.ui.requestTitle(approval.requestNumber)}
                  categoryName={item?.equipment_category_name}
                  status={t.approvalTag[approval.kind]}
                  accent
                  details={decisionSubtitle(decision) ?? (item ? undefined : approval.label)}
                  fill
                />
              );
            })}
          </div>
        </section>
      )}
    </>
  );

  const myPanel = (
    <>
      {loading && <SkeletonRows rows={3} />}
      {hasError && <ErrorState message={t.loadError} error={loadError} onRetry={retryAll} />}

      {!loading && (working.length > 0 || nothing) && (
        <section className="home-section" aria-labelledby="home-working">
          <SectionCaption id="home-working" large>
            {t.nowInWork}
          </SectionCaption>
          {working.length > 0 ? (
            <div className="home-cards">
              {working.map((item) => {
                const line = listStatus(item, { isManager });
                return (
                  <HomeCard
                    key={item.id}
                    to={`/requests/${item.id}`}
                    title={listItemEquipmentName(item)}
                    categoryName={item.equipment_category_name}
                    status={line.text}
                    accent={line.accent}
                  />
                );
              })}
            </div>
          ) : (
            <div className="home-find__lead">
              <p className="home-find__text">{isManager ? t.emptyText : t.emptyEmployeeText}</p>
            </div>
          )}
        </section>
      )}

      {!loading && drafts.length > 0 && (
        <section className="home-section" aria-labelledby="home-drafts">
          <SectionCaption id="home-drafts" large>
            {t.drafts}
          </SectionCaption>
          <List>
            {drafts.map((item) => (
              <ListRow
                key={item.id}
                media={equipmentIllustration(null, item.equipment_category_name ?? item.equipment_title)}
                title={listItemEquipmentName(item)}
                subtitle={t.draftSaved(relativeDay(item.updated_at, item.timezone))}
                to={`/requests/${item.id}`}
                chevron
              />
            ))}
          </List>
        </section>
      )}

      {pointEquipment.length > 0 && (
        <section className="home-section" aria-labelledby="home-equipment">
          <SectionCaption
            id="home-equipment"
            large
            action={<Link to="/equipment">{t.equipmentAll(pointEquipment.length)}</Link>}
          >
            {t.equipmentTitle}
          </SectionCaption>
          <List>
            {pointEquipment.slice(0, EQUIPMENT_PREVIEW).map((item) => (
              <ListRow
                key={item.id}
                media={equipmentIllustration(item.category_code, item.category_name)}
                title={equipmentTitle(item)}
                subtitle={equipmentSubtitle(item)}
                to={`/equipment/${item.location_id}/${item.id}`}
              />
            ))}
          </List>
        </section>
      )}
    </>
  );

  const providersCount = providers.data ?? 0;
  const canFind = Boolean(point) && providers.isSuccess && providersCount > 0;
  const findLead = !point ? (
    <div className="home-find__lead">
      <h2 className="home-find__title">{t.pickPointTitle}</h2>
      <p className="home-find__text">{t.pickPointText}</p>
    </div>
  ) : providers.isPending ? (
    <SkeletonRows rows={2} />
  ) : providers.isError ? (
    <ErrorState error={providers.error} onRetry={() => void providers.refetch()} top={16} />
  ) : providersCount > 0 ? (
    <>
      <div className="home-find__lead">
        <h2 className="home-find__title">{t.findTitle}</h2>
        <p className="home-find__text">{isManager ? t.findText : t.findTextEmployee}</p>
      </div>
      <List>
        <ListRow title={t.providersNearby} value={String(providersCount)} valueTone="strong" />
      </List>
    </>
  ) : (
    <div className="home-find__lead">
      <h2 className="home-find__title">{t.providersNone}</h2>
      <p className="home-find__text">{t.providersNoneText}</p>
    </div>
  );

  const findPanel = (
    <>
      <SceneBanner name="status-search" height={170} width={210} />
      {findLead}
      {searching.length > 0 && (
        <section className="home-section" aria-labelledby="home-searching">
          <SectionCaption id="home-searching">{t.searching}</SectionCaption>
          <List>
            {searching.map((item) => (
              <ListRow
                key={item.id}
                media={equipmentIllustration(null, item.equipment_category_name ?? item.equipment_title)}
                title={listItemEquipmentName(item)}
                subtitle={listStatus(item, { isManager }).text}
                to={`/requests/${item.id}`}
                chevron
              />
            ))}
          </List>
        </section>
      )}
    </>
  );

  const bottomAction =
    tab === 'my' ? (
      <ActionButton to="/requests/new">
        <PlusIcon className="home-cta__icon" />
        {t.newRequest}
      </ActionButton>
    ) : canFind ? (
      <ActionButton to="/requests/new?route=marketplace">
        <PlusIcon className="home-cta__icon" />
        {t.describeProblem}
      </ActionButton>
    ) : !point && points.length > 1 ? (
      <ActionButton kind="s" onClick={() => setPointsOpen(true)}>
        {t.pickPoint}
      </ActionButton>
    ) : null;

  return (
    <Screen
      title={strings.ui.appTitle}
      hideHeader
      actions={bottomAction ? <BottomActions>{bottomAction}</BottomActions> : undefined}
    >
      <h1 className="ui-visually-hidden">{t.heading}</h1>
      <div className="home-top">
        <div className="home-top__context">
          {/* Организация видна всегда: при нескольких членствах иначе непонятно, чья это главная. */}
          <span className="home-org">{organizationName}</span>
          {points.length > 1 ? (
            <button
              type="button"
              className="home-point"
              aria-haspopup="dialog"
              aria-label={t.pointChange(pointName ?? t.allPoints)}
              onClick={() => setPointsOpen(true)}
            >
              {pointHeader}
            </button>
          ) : (
            <div className="home-point">{pointHeader}</div>
          )}
        </div>
        <button
          type="button"
          className="home-avatar"
          aria-label={strings.ui.menu}
          aria-haspopup="dialog"
          onClick={() => setMenuOpen(true)}
        >
          <span aria-hidden="true">{initials(user?.display_name ?? activeMembership.organization.name)}</span>
        </button>
      </div>

      {decisionsBlock}

      <SegmentTabs
        label={t.routeTabsLabel}
        idPrefix="home-tab"
        items={[
          { id: 'my', label: t.myService },
          { id: 'find', label: t.findProvider },
        ]}
        value={tab}
        onChange={setTab}
      />
      {/* Обычный блок, а не display: contents — иначе WebKit выбрасывает роль tabpanel из дерева доступности. */}
      <div
        id="home-tab-panel"
        role="tabpanel"
        aria-labelledby={`home-tab-${tab}`}
        style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}
      >
        {tab === 'my' ? myPanel : findPanel}
      </div>

      <Sheet open={pointsOpen} onClose={() => setPointsOpen(false)} title={t.pointPickerTitle}>
        <List role="radiogroup" aria-label={t.pointPickerTitle}>
          {[{ id: '', name: t.allPoints }, ...points].map((location) => (
            <ListRow
              key={location.id || 'all'}
              title={location.name}
              control={{ type: 'radio', checked: (point?.id ?? '') === location.id }}
              onToggle={() => {
                setPointId(location.id);
                setPointsOpen(false);
              }}
            />
          ))}
        </List>
      </Sheet>

      <Sheet
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        title={organizationName}
        description={layout.activeContext?.role}
      >
        <List>
          <ListRow
            title={strings.header.switchOrganization}
            action="accent"
            onClick={() => {
              setMenuOpen(false);
              layout.switchOrganization();
            }}
          />
        </List>
      </Sheet>
    </Screen>
  );
}
