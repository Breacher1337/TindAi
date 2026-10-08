/**
 * TindAI Offline Store & Background Sync Dispatcher (Milestone 2)
 * Manages browser IndexedDB database (TindAIDB, v1) for queueing offline
 * POS checkout transactions with sync_status="PENDING_OFFLINE" and auto-sync on reconnection.
 */

(function () {
  'use strict';

  const DB_NAME = 'TindAIDB';
  const DB_VERSION = 1;
  const STORE_NAME = 'offline_transactions';

  let dbPromise = null;
  let isSyncing = false;

  function generateUUID() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function getCsrfToken() {
    const metaToken = document.querySelector('[name=csrfmiddlewaretoken]');
    if (metaToken && metaToken.value) return metaToken.value;

    const cookieMatch = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    if (cookieMatch) return decodeURIComponent(cookieMatch[1]);

    try {
      const bodyHx = document.body.getAttribute('hx-headers');
      if (bodyHx) {
        const parsed = JSON.parse(bodyHx);
        if (parsed['X-CSRFToken']) return parsed['X-CSRFToken'];
      }
    } catch (_) {}
    return '';
  }

  function initDB() {
    if (dbPromise) return dbPromise;

    dbPromise = new Promise((resolve, reject) => {
      if (typeof indexedDB === 'undefined') {
        reject(new Error('IndexedDB is not supported in this environment.'));
        return;
      }

      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' });
          store.createIndex('sync_status', 'sync_status', { unique: false });
          store.createIndex('timestamp', 'timestamp', { unique: false });
        }
      };

      request.onsuccess = (event) => {
        resolve(event.target.result);
      };

      request.onerror = (event) => {
        console.error('[TindAIDB] Failed to open IndexedDB:', event.target.error);
        reject(event.target.error);
      };
    });

    return dbPromise;
  }

  function saveOfflineTransaction(tx) {
    return initDB().then((db) => {
      return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);

        const record = {
          id: tx.id || generateUUID(),
          transaction_type: (tx.transaction_type || 'CASH').toUpperCase(),
          items: tx.items || [],
          customer_id: tx.customer_id || null,
          total_amount: tx.total_amount ? String(tx.total_amount) : '0.00',
          sync_status: 'PENDING_OFFLINE',
          timestamp: tx.timestamp || new Date().toISOString(),
          notes: tx.notes || 'Offline POS transaction'
        };

        const request = store.put(record);

        request.onsuccess = () => {
          // Register background sync tag if Service Worker is active
          if ('serviceWorker' in navigator && 'SyncManager' in window) {
            navigator.serviceWorker.ready.then((reg) => {
              reg.sync.register('sync-offline-transactions').catch(() => {});
            }).catch(() => {});
          }
          resolve(record);
        };

        request.onerror = (event) => {
          console.error('[TindAIDB] Failed to save transaction:', event.target.error);
          reject(event.target.error);
        };
      });
    });
  }

  function getPendingOfflineTransactions() {
    return initDB().then((db) => {
      return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.getAll();

        request.onsuccess = () => {
          const all = request.result || [];
          const pending = all.filter((item) => item.sync_status === 'PENDING_OFFLINE');
          resolve(pending);
        };

        request.onerror = (event) => {
          reject(event.target.error);
        };
      });
    });
  }

  function markTransactionSynced(id) {
    return initDB().then((db) => {
      return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const getReq = store.get(id);

        getReq.onsuccess = () => {
          const record = getReq.result;
          if (record) {
            record.sync_status = 'SYNCED';
            record.synced_at = new Date().toISOString();
            const putReq = store.put(record);
            putReq.onsuccess = () => resolve(record);
            putReq.onerror = (e) => reject(e.target.error);
          } else {
            resolve(null);
          }
        };

        getReq.onerror = (event) => {
          reject(event.target.error);
        };
      });
    });
  }

  function deleteOfflineTransaction(id) {
    return initDB().then((db) => {
      return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.delete(id);

        request.onsuccess = () => resolve(true);
        request.onerror = (event) => reject(event.target.error);
      });
    });
  }

  async function syncOfflineTransactions() {
    if (isSyncing) return { synced: 0, total: 0, status: 'already_syncing' };
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      return { synced: 0, total: 0, status: 'offline' };
    }

    isSyncing = true;
    let syncedCount = 0;
    let pendingList = [];

    try {
      pendingList = await getPendingOfflineTransactions();
      if (!pendingList.length) {
        isSyncing = false;
        return { synced: 0, total: 0, status: 'idle' };
      }

      const csrf = getCsrfToken();

      for (const tx of pendingList) {
        const payload = {
          id: tx.id,
          sync_status: 'PENDING_OFFLINE',
          transaction_type: tx.transaction_type || 'CASH',
          customer_id: tx.customer_id || null,
          items: (tx.items || []).map((it) => ({
            product_id: it.product_id || it.id,
            quantity: parseFloat(it.quantity || it.qty || 1)
          })),
          notes: tx.notes || 'Offline checkout synced'
        };

        try {
          const response = await fetch('/api/transactions', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrf
            },
            body: JSON.stringify(payload)
          });

          if (response.ok) {
            const data = await response.json();
            await markTransactionSynced(tx.id);
            syncedCount++;

            // Dispatch global event for UI notifications/toasts
            if (typeof window !== 'undefined') {
              window.dispatchEvent(
                new CustomEvent('tindai:offline_synced', {
                  detail: { id: tx.id, result: data }
                })
              );
            }
          } else {
            console.warn('[TindAIDB] Server rejected transaction during sync:', tx.id, response.status);
          }
        } catch (postErr) {
          console.warn('[TindAIDB] Network failure syncing transaction:', tx.id, postErr);
        }
      }
    } catch (err) {
      console.error('[TindAIDB] Error in syncOfflineTransactions:', err);
    } finally {
      isSyncing = false;
    }

    return { synced: syncedCount, total: pendingList.length, status: 'completed' };
  }

  // Setup automatic listeners for reconnection
  if (typeof window !== 'undefined') {
    window.addEventListener('online', () => {
      console.log('[TindAIDB] Network reconnected. Flushing offline queue...');
      syncOfflineTransactions();
    });

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'TRIGGER_OFFLINE_SYNC') {
          syncOfflineTransactions();
        }
      });
    }
  }

  // Export module to global scope
  const OfflineStore = {
    initDB,
    generateUUID,
    saveOfflineTransaction,
    getPendingOfflineTransactions,
    markTransactionSynced,
    deleteOfflineTransaction,
    syncOfflineTransactions
  };

  if (typeof window !== 'undefined') {
    window.TindAIOfflineStore = OfflineStore;
    window.saveOfflineTransaction = saveOfflineTransaction;
    window.getPendingOfflineTransactions = getPendingOfflineTransactions;
    window.markTransactionSynced = markTransactionSynced;
    window.deleteOfflineTransaction = deleteOfflineTransaction;
    window.syncOfflineTransactions = syncOfflineTransactions;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = OfflineStore;
  }
})();
