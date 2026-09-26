import { strings } from '../../../strings/ru';
import { Avatar } from '../../../ui/blocks/Blocks';
import type { ProviderRatingSummary } from '../../../api/types';
import { ratingLine } from './cardModel';
import '../../../components/request/request.css';

function PhoneIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function CardPerson({
  name,
  company,
  rating,
  phone,
}: {
  name: string;
  company?: string | null;
  rating?: ProviderRatingSummary | null;
  phone?: string | null;
}) {
  const sub = [company && company !== name ? company : null, ratingLine(rating ?? null)]
    .filter(Boolean)
    .join(' · ');
  const tel = phone?.trim() ? `tel:${phone.replace(/[^\d+]/g, '')}` : null;
  return (
    <div className="request-person">
      <Avatar name={name} size={48} aria-hidden />
      <div className="request-person__main">
        <span className="request-person__name">{name}</span>
        {sub && <span className="request-person__sub">{sub}</span>}
      </div>
      {tel && (
        <a
          className="request-round"
          href={tel}
          aria-label={strings.requests.card.callProviderNamed(name)}
        >
          <PhoneIcon />
        </a>
      )}
    </div>
  );
}
