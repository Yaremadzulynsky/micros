/* Local explanatory models only: no network, device access, or automatic playback. */
(() => {
  'use strict';

  function put(root, values) {
    for (const [key, value] of Object.entries(values)) {
      root.querySelectorAll(`[data-field="${key}"]`).forEach(node => { node.textContent = value; });
    }
  }

  function selectStep(root, index) {
    root.dataset.step = String(index);
    root.querySelectorAll('button[data-step]').forEach(button => {
      const selected = Number(button.dataset.step) === index;
      button.setAttribute('aria-pressed', String(selected));
      if (selected) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
  }

  const helloSteps = [
    {
      'editor-label': 'Current source', 'source-version': '1.0.0',
      'build-note': 'Compiled for this device and its base.', 'device-state': 'Running',
      'running-version': 'v1.0.0', 'application-state': 'Timer callback every second',
      output: 'Hello world\nHello world',
      summary: 'Hello runs on the device. Its repeating timer writes a message through the base’s diagnostic API.'
    },
    {
      'editor-label': 'Proposed source change', 'source-version': '1.0.0 → 1.1.0',
      'build-note': 'Local edits only. The device still runs v1.0.0.', 'device-state': 'Running',
      'running-version': 'v1.0.0', 'application-state': 'Original application still running',
      output: 'Hello world\nHello world',
      summary: 'Edit the message and bump the service version. The old application keeps running until you deploy the change.'
    },
    {
      'editor-label': 'Build and stage', 'source-version': '1.1.0',
      'build-note': 'Graph validated; images and configuration are being staged.', 'device-state': 'Paused',
      'running-version': 'Services stopped', 'application-state': 'The complete selected graph pauses',
      output: '— application paused for staging —',
      summary: 'The application stops while the complete graph is staged. Resident management remains available during this normal update path.'
    },
    {
      'editor-label': 'Updated source', 'source-version': '1.1.0',
      'build-note': 'Built and validated against the same base.', 'device-state': 'Running',
      'running-version': 'v1.1.0', 'application-state': 'New message, same lifecycle',
      output: 'Hello from hello v2\nHello from hello v2',
      summary: 'After activation and liveness confirmation, hello produces the new message. Inspect the actual output to check that the change does what you intended.'
    }
  ];

  function initHello(root) {
    const render = index => { selectStep(root, index); put(root, helloSteps[index]); };
    root.querySelectorAll('button[data-step]').forEach(button => {
      button.addEventListener('click', () => render(Number(button.dataset.step)));
    });
    render(0);
  }

  const resources = {
    timer: {
      'declaration-file': 'service.toml', declaration: '[service.capabilities]\ntimers = 1',
      code: 'timer_open(..., print_hello,\n           ..., &state->timer);',
      'resource-title': 'One open timer',
      'resource-detail': 'start opens it · callback writes the message · stop closes it',
      summary: 'The declaration permits one open timer. Opening it uses that budget; declaring a timer does not schedule the callback.'
    },
    arena: {
      'declaration-file': 'service.c · descriptor', declaration: '.arena_bytes =\n    sizeof(hello_state_t),',
      code: 'hello_state_t *state =\n    service_args->arena;',
      'resource-title': 'One arena for this service instance',
      'resource-detail': 'Zeroed before init · retained during execution · reclaimed after the worker stops',
      summary: 'The base reserves the declared arena. Hello stores its timer handle there; sizeof follows the state type when its fields change.'
    },
    stack: {
      'declaration-file': 'service.c · descriptor', declaration: '.stack_bytes = 4096,',
      code: '.start = start,\n.step = step,\n.stop = stop,',
      'resource-title': 'A 4 KiB worker-stack request',
      'resource-detail': 'Lifecycle hooks and timer callbacks share one worker',
      summary: 'Hello requests a worker stack separately from its instance arena. Platform limits and stack rounding still apply; 4 KiB is this source example’s request.'
    }
  };

  function initContract(root) {
    const render = key => {
      root.dataset.resource = key;
      root.querySelectorAll('[data-resource]').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.resource === key));
      });
      put(root, resources[key]);
    };
    root.querySelectorAll('button[data-resource]').forEach(button => {
      button.addEventListener('click', () => render(button.dataset.resource));
    });
    render('timer');
  }

  function initMemory(root) {
    const input = root.querySelector('input[type="range"]');
    const limit = 8; // ESP32 flash-service instruction + constant slot, in KiB.
    const render = () => {
      const request = Number(input.value);
      const fits = request <= limit;
      root.dataset.fits = String(fits);
      root.querySelector('.budget-fill').style.width = `${request / 12 * 100}%`;
      root.querySelector('.budget-track').setAttribute('aria-label',
        `Illustrative request: ${request} KiB. Code slot limit: ${limit} KiB. Scale: 0 to 12 KiB.`);
      input.setAttribute('aria-valuetext', `${request} KiB; ${fits ? 'within' : 'exceeds'} the code-slot limit`);
      put(root, {
        requested: `${request} KiB`,
        summary: fits
          ? `${request} KiB fits within the 8 KiB code slot. Passing this check does not establish that the whole application fits.`
          : `${request} KiB exceeds the 8 KiB code slot. This candidate is rejected before deployment; unused space in another memory budget does not enlarge the code slot.`
      });
    };
    input.addEventListener('input', render);
    render();
  }

  const validate = {
    running: 'v1.0.0 running', 'running-detail': 'The existing application continues during validation',
    bank0: 'Selected · known good', bank1: 'Inactive · candidate not staged',
    management: 'Management available', connection: 'Connected', active: '0', bankState: 'empty',
    summary: 'Check the target base, packages, interfaces, and resource budgets before stopping services. The current good selection stays in bank 0.'
  };
  const stage = {
    running: 'All services stopped', 'running-detail': 'Application downtime includes staging the complete graph',
    bank0: 'Known good · retained', bank1: 'Writing candidate · not selected',
    management: 'Management available', connection: 'Connected', active: '', bankState: 'partial',
    summary: 'Images and configuration are written to bank 1 while the graph is stopped. Bank 0 remains the good selection. Partial staged bytes cannot be activated.'
  };
  const recovered = {
    running: 'v1.0.0 running again', 'running-detail': 'The original graph was restarted after reconnecting',
    bank0: 'Selected · known good', bank1: 'Incomplete content · not selected',
    management: 'Management available', connection: 'Reconnected', active: '0', bankState: 'partial',
    summary: 'After reconnection, status confirms the same good selection and no pending trial. The client restarts that graph and verifies it is running. Until status returns, recovery is unconfirmed.'
  };
  const scenarios = {
    success: {
      labels: ['Validate', 'Stage', 'Activate', 'Confirm'],
      states: [validate, stage, {
        running: 'v1.1.0 on trial', 'running-detail': 'The candidate is running; it is not yet confirmed good',
        bank0: 'Known good · retained', bank1: 'Candidate trial · running',
        management: 'Management available', connection: 'Connected', active: '1', bankState: 'complete',
        summary: 'The admitted candidate starts from bank 1. ESP32 checks Running state, reported results, and execution progress over a five-second liveness window.'
      }, {
        running: 'v1.1.0 running', 'running-detail': 'Candidate confirmed after runtime liveness checks',
        bank0: 'Previous application retained', bank1: 'Selected · newly confirmed good',
        management: 'Management available', connection: 'Connected', active: '1', bankState: 'complete',
        summary: 'The confirmation record makes bank 1 the new good selection. Bank 0 retains the previous application. Runtime liveness does not prove that the diagnostic output or physical behavior is correct.'
      }]
    },
    transfer: {
      labels: ['Validate', 'Stage', 'Interrupted', 'Recover'],
      states: [validate, stage, {
        running: 'Services stopped at interruption', 'running-detail': 'No candidate was activated in this example',
        bank0: 'Known good selection retained', bank1: 'Incomplete content · not selected',
        management: 'No fresh observation until reconnect', connection: 'Connection lost', active: '', bankState: 'partial',
        summary: 'The transfer stops before activation. Bank 0 is still the recorded good selection, but the client cannot confirm current execution while disconnected.'
      }, recovered]
    },
    candidate: {
      labels: ['Validate', 'Stage', 'Trial fails', 'Fall back'],
      states: [validate, stage, {
        running: 'Candidate failed to start', 'running-detail': 'Failed boot attempts are persisted before retrying',
        bank0: 'Known good · retained', bank1: 'Candidate failed · trial allowance consumed',
        management: 'May disconnect during trial resets', connection: 'Reboot / reconnect', active: '', bankState: 'failed',
        summary: 'This candidate fails startup. The controller resets and retries within the two-attempt allowance; service update recovery can therefore include device reboots.'
      }, {
        running: 'v1.0.0 running again', 'running-detail': 'The candidate has exhausted its two boot attempts',
        bank0: 'Selected · known good', bank1: 'Failed candidate · not selected',
        management: 'Management available after reboot', connection: 'Reconnected', active: '0', bankState: 'failed',
        summary: 'After two failed candidate boot attempts, the device falls back to the prior good graph. This example starts with a valid confirmed application; without one, recovery is required.'
      }]
    }
  };

  function initUpdate(root) {
    const selector = root.querySelector('select');
    const previous = root.querySelector('[data-previous]');
    const next = root.querySelector('[data-next]');
    let scenario = Object.hasOwn(scenarios, selector.value) ? selector.value : 'success';
    let index = 0;
    const render = () => {
      const current = scenarios[scenario];
      const state = current.states[index];
      selectStep(root, index);
      root.dataset.scenario = scenario;
      root.dataset.bankState = state.bankState;
      root.querySelectorAll('[data-stage-label]').forEach((label, i) => { label.textContent = current.labels[i]; });
      root.querySelectorAll('[data-bank]').forEach(bank => { bank.dataset.active = String(bank.dataset.bank === state.active); });
      put(root, {...state, position: `${index + 1} of ${current.states.length}`});
      previous.disabled = index === 0;
      next.disabled = index === current.states.length - 1;
    };
    selector.addEventListener('change', () => { scenario = selector.value; index = 0; render(); });
    root.querySelectorAll('button[data-step]').forEach(button => {
      button.addEventListener('click', () => { index = Number(button.dataset.step); render(); });
    });
    previous.addEventListener('click', () => { if (index > 0) index--; render(); });
    next.addEventListener('click', () => { if (index < scenarios[scenario].states.length - 1) index++; render(); });
    render();
  }

  const initializers = {hello: initHello, contract: initContract, memory: initMemory, update: initUpdate};
  function init() {
    document.querySelectorAll('[data-demo]').forEach(root => {
      if (root.dataset.ready || !Object.hasOwn(initializers, root.dataset.demo)) return;
      initializers[root.dataset.demo](root);
      root.dataset.ready = 'true';
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
