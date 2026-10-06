# Shared toolchain settings: build with the Command Line Tools (works without accepting the Xcode
# licence) and point SwiftPM at Swift Testing, which CLT ships outside the default search path.
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}"
F1LAP_TEST_FRAMEWORKS="$DEVELOPER_DIR/Library/Developer/Frameworks"
F1LAP_TEST_LIBS="$DEVELOPER_DIR/Library/Developer/usr/lib"
F1LAP_TEST_FLAGS=(
  -Xswiftc -F -Xswiftc "$F1LAP_TEST_FRAMEWORKS"
  -Xlinker -F -Xlinker "$F1LAP_TEST_FRAMEWORKS"
  -Xlinker -rpath -Xlinker "$F1LAP_TEST_FRAMEWORKS"
  -Xlinker -rpath -Xlinker "$F1LAP_TEST_LIBS"
)
