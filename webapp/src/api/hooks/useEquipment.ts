import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { equipmentChanged } from '../invalidation';
import { queryKeys } from '../queryKeys';
import type { Attachment, Equipment, EquipmentInput, EquipmentUpdateInput, Page } from '../types';

export function useEquipmentList(locationId?: string) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.equipment(scope, locationId),
    queryFn: async () =>
      (await api.get<Page<Equipment>>('/equipment', { query: { location_id: locationId } })).items,
    enabled: Boolean(scope && locationId),
  });
}

export function useOrgEquipment() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.equipment(scope, undefined),
    queryFn: async () => (await api.get<Page<Equipment>>('/equipment')).items,
    enabled: Boolean(scope),
  });
}

export function useEquipmentItem(id: string | undefined) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.equipmentItem(scope, id ?? ''),
    queryFn: () => api.get<Equipment>(`/equipment/${id}`),
    enabled: Boolean(scope && id),
  });
}

export function useCreateEquipment() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: EquipmentInput, idempotencyKey) =>
      api.post<Equipment>('/equipment', input, { idempotencyKey }),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.equipment(scope, created.location_id),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.equipment(scope, undefined) });
    },
  });
}

export function useUpdateEquipment(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: EquipmentUpdateInput, idempotencyKey) =>
      api.patch<Equipment>(`/equipment/${id}`, input, { idempotencyKey }),
    onSuccess: () => equipmentChanged(queryClient, scope),
  });
}

export function useEquipmentPhotos(equipmentId: string | undefined) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.equipmentPhotos(scope, equipmentId ?? ''),
    queryFn: () => api.get<Attachment[]>(`/equipment/${equipmentId}/photos`),
    enabled: Boolean(scope && equipmentId),
  });
}

export function useUploadEquipmentPhoto() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (
      { equipmentId, file, slot }: { equipmentId: string; file: File; slot?: string },
      idempotencyKey,
    ) => {
      const form = new FormData();
      form.append('file', file);
      if (slot) form.append('slot', slot);
      return api.post<Attachment>(`/equipment/${equipmentId}/photos`, form, { idempotencyKey });
    },
    onSuccess: () => {
      equipmentChanged(queryClient, scope);
    },
  });
}
