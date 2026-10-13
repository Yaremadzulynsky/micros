# Micros

**Build microcontroller applications from native C and C++ services.**

Micros provides service lifecycle management, typed messages, remote inspection
and application updates on top of the resident OS.

[Documentation](https://docs.meetmicros.com/) ·
[Quickstart](https://docs.meetmicros.com/site/get-started/) ·
[Tutorials](https://docs.meetmicros.com/tutorials) ·
[Architecture](https://docs.meetmicros.com/site/architecture/)

## 01 · Get the SDK

Use macOS or Linux with Git to clone the SDK. No board or server needed.
Choose an unused SDK directory:

```sh
mkdir -p "$HOME/tools"
git clone --branch main https://github.com/Yaremadzulynsky/micros.git "$HOME/tools/micros"
cd "$HOME/tools/micros"
./micros setup

export MICROS_SDK="$HOME/tools/micros"
export PATH="$MICROS_SDK:$PATH"
```

`setup` checks your computer and installs missing development tools and Python
dependencies. Use `./micros setup --check` to check without installing. See
[setup requirements](https://docs.meetmicros.com/site/install-the-sdk/#setup-requirements)
for package managers and administrator access.

Add the two exports to your shell's startup file to keep them for new terminals.

## 02 · Create your project

From the same terminal, create your application outside the SDK checkout:

```sh
cd "$HOME"
micros new my-application
cd my-application
```

## 03 · Continue in the docs

**[Follow the quickstart →](https://docs.meetmicros.com/site/get-started/#create-your-project)**
Run `./micros enroll` to choose or create a server, install the runtime and deploy
the simulated climate starter. No sensors or actuators are required.
Without a board, [run locally](https://docs.meetmicros.com/site/run-locally/).

Next, [learn the micros way](https://docs.meetmicros.com/tutorials): connect a clock
service to an LED, then replace the clock with a button while reusing the LED
service. The [runnable examples and tests](examples/tutorials/toggle/README.md)
are maintained in this repository.

Working on Micros itself? See the [contributor guide](https://docs.meetmicros.com/site/contributing/).

---

[MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
