import { useRef, useState } from 'react';
import { strings } from '../../strings/ru';
import {
  useDeletePortfolioImage,
  usePortfolio,
  useProviderProfile,
  useUpdatePortfolioCaption,
  useUploadPortfolioImage,
} from '../../api/hooks/useProviderProfile';
import type { Attachment } from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, PageTitle } from '../../ui/blocks/Blocks';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../ui/PhotoGrid';
import { Sheet } from '../../ui/Sheet';
import { TextField } from '../../ui/FormField';

export const DEFAULT_PORTFOLIO_LIMIT = 10;
const CAPTION_MAX = 200;

const TILE: Record<Attachment['processing_state'], PhotoState> = {
  ready: 'ok',
  quarantined: 'q',
  rejected: 'e',
};

const TILE_LABEL: Record<Attachment['processing_state'], string | undefined> = {
  ready: undefined,
  quarantined: strings.provider.portfolioStateQuarantined,
  rejected: strings.provider.portfolioStateRejected,
};

function tileLabel(item: Attachment) {
  return TILE_LABEL[item.processing_state] ?? item.caption ?? undefined;
}

export function ProviderPortfolioSection() {
  const portfolio = usePortfolio();
  const profile = useProviderProfile();
  const upload = useUploadPortfolioImage();
  const remove = useDeletePortfolioImage();
  const updateCaption = useUpdatePortfolioCaption();
  const fileInput = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<{ attachment: Attachment; index: number } | null>(null);
  const [caption, setCaption] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sheetError, setSheetError] = useState<string | null>(null);

  const open = (attachment: Attachment, index: number) => {
    setSheetError(null);
    setCaption(attachment.caption ?? '');
    setSelected({ attachment, index });
  };

  const items = portfolio.data ?? [];
  const limit = profile.data?.portfolio_max_images ?? DEFAULT_PORTFOLIO_LIMIT;
  const limitReached = items.length >= limit;
  const rejected = items.filter((item) => item.processing_state === 'rejected');

  const pick = () => fileInput.current?.click();

  const handleFile = async (file: File) => {
    setError(null);
    try {
      await upload.mutateAsync(file);
    } catch (e) {
      setError(actionErrorMessage(e, strings.provider.portfolioUploadError));
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    setSheetError(null);
    try {
      await remove.mutateAsync(selected.attachment.id);
      setSelected(null);
    } catch (e) {
      setSheetError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  const savedCaption = selected?.attachment.caption ?? '';
  const captionChanged = caption.trim() !== savedCaption;
  const handleCaption = async () => {
    if (!selected) return;
    setSheetError(null);
    try {
      await updateCaption.mutateAsync({
        attachmentId: selected.attachment.id,
        caption: caption.trim() || null,
      });
      setSelected(null);
    } catch (e) {
      setSheetError(actionErrorMessage(e, strings.provider.portfolioCaptionError));
    }
  };
  const sheetBusy = remove.isPending || updateCaption.isPending;

  return (
    <Screen
      title={strings.provider.portfolioScreenTitle}
      back="/provider/profile"
      actions={
        <BottomActions>
          <ActionButton
            kind="s"
            loading={upload.isPending}
            disabled={limitReached || !portfolio.isSuccess}
            onClick={pick}
          >
            {strings.provider.portfolioUpload}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle subtitle={strings.provider.portfolioHintLimit(limit)}>
        {strings.provider.portfolioWorksTitle}
      </PageTitle>

      {portfolio.isPending && <Skeleton lines={2} />}
      {portfolio.isError && (
        <ErrorState error={portfolio.error} onRetry={() => void portfolio.refetch()} />
      )}

      {portfolio.isSuccess && (
        <PhotoGrid label={strings.provider.portfolioTitle}>
          {items.map((item, index) => (
            <PhotoTile
              key={item.id}
              state={TILE[item.processing_state]}
              attachmentId={item.id}
              alt={strings.attachments.portfolioAlt(index + 1)}
              label={tileLabel(item)}
              actionLabel={strings.provider.portfolioOpen(index + 1)}
              onClick={() => open(item, index + 1)}
            />
          ))}
          {!limitReached && (
            <PhotoTile
              state="add"
              label={strings.provider.portfolioAddTile}
              actionLabel={strings.provider.portfolioUpload}
              disabled={upload.isPending}
              onClick={pick}
            />
          )}
        </PhotoGrid>
      )}

      {portfolio.isSuccess && items.length === 0 && <Note>{strings.provider.portfolioEmpty}</Note>}
      {rejected.map((item) => (
        <Note key={item.id} tone="error">
          {strings.provider.portfolioRejectedNote(
            item.rejected_reason ?? strings.provider.portfolioRejectedDefault,
          )}
        </Note>
      ))}
      {limitReached && <Note>{strings.provider.portfolioLimitReached}</Note>}
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}

      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        hidden
        aria-label={strings.provider.portfolioUpload}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (file) void handleFile(file);
        }}
      />

      <Sheet
        open={selected !== null}
        title={selected ? strings.attachments.portfolioAlt(selected.index) : undefined}
        description={
          selected
            ? (TILE_LABEL[selected.attachment.processing_state] ??
              (selected.attachment.publication_state === 'pending'
                ? strings.provider.portfolioOnModeration
                : undefined))
            : undefined
        }
        onClose={() => setSelected(null)}
        locked={sheetBusy}
        actions={
          <>
            <ActionButton
              loading={updateCaption.isPending}
              disabled={!captionChanged || remove.isPending}
              onClick={() => void handleCaption()}
            >
              {strings.provider.portfolioCaptionSave}
            </ActionButton>
            <ActionButton
              kind="d"
              loading={remove.isPending}
              disabled={updateCaption.isPending}
              onClick={() => void handleDelete()}
            >
              {strings.provider.portfolioDelete}
            </ActionButton>
            <ActionButton kind="s" disabled={sheetBusy} onClick={() => setSelected(null)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      >
        {selected && (
          <>
            <PhotoGrid>
              <PhotoTile
                state={TILE[selected.attachment.processing_state]}
                attachmentId={selected.attachment.id}
                alt={strings.attachments.portfolioAlt(selected.index)}
              />
            </PhotoGrid>
            <TextField
              id="portfolio-caption"
              label={strings.provider.portfolioCaptionLabel}
              placeholder={strings.provider.portfolioCaptionPlaceholder}
              hint={strings.provider.portfolioCaptionHint}
              maxLength={CAPTION_MAX}
              value={caption}
              onChange={setCaption}
            />
            {sheetError && (
              <Note tone="error" role="alert">
                {sheetError}
              </Note>
            )}
          </>
        )}
      </Sheet>
    </Screen>
  );
}
