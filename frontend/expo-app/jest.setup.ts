type Listener = (event: Record<string, unknown>) => void;

const mockSecureStore = new Map<string, string>();

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn((key: string) => Promise.resolve(mockSecureStore.get(key) ?? null)),
  setItemAsync: jest.fn((key: string, value: string) => {
    mockSecureStore.set(key, value);
    return Promise.resolve();
  }),
  deleteItemAsync: jest.fn((key: string) => {
    mockSecureStore.delete(key);
    return Promise.resolve();
  }),
}));

jest.mock('react-native-sse', () => {
  class MockEventSource {
    static instances: MockEventSource[] = [];

    url: string;
    options: Record<string, unknown>;
    closed = false;
    listeners = new Map<string, Listener[]>();

    constructor(url: string, options: Record<string, unknown> = {}) {
      this.url = url;
      this.options = options;
      MockEventSource.instances.push(this);
    }

    addEventListener(type: string, listener: Listener) {
      this.listeners.set(type, [...(this.listeners.get(type) || []), listener]);
    }

    removeEventListener(type: string, listener: Listener) {
      this.listeners.set(type, (this.listeners.get(type) || []).filter((item) => item !== listener));
    }

    removeAllEventListeners(type?: string) {
      if (type) {
        this.listeners.delete(type);
        return;
      }
      this.listeners.clear();
    }

    close() {
      this.closed = true;
    }

    emit(type: string, event: Record<string, unknown> = {}) {
      (this.listeners.get(type) || []).forEach((listener) => listener({ type, ...event }));
    }

    static reset() {
      MockEventSource.instances = [];
    }
  }

  return {
    __esModule: true,
    default: MockEventSource,
  };
});

beforeEach(() => {
  mockSecureStore.clear();
  global.fetch = jest.fn();
});
