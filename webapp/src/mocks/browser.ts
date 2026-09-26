import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';
import { setDeliveryOverride } from './requestsDb';

export const worker = setupWorker(...handlers);

(window as unknown as { __mockControl?: unknown }).__mockControl = { setDeliveryOverride };
