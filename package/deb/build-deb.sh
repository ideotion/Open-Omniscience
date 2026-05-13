#!/bin/bash
# Open Omniscience Debian Package Builder
# This script creates a .deb package for the Open Omniscience application

set -e

# Configuration
APP_NAME="open-omniscience"
APP_VERSION="0.2.0"
PACKAGE_NAME="${APP_NAME}_${APP_VERSION}_all"
BUILD_DIR="build-deb"
OUTPUT_DIR="dist"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Clean up previous builds
cleanup() {
    echo -e "${YELLOW}Cleaning up previous builds...${NC}"
    rm -rf "$BUILD_DIR" "$OUTPUT_DIR" *.deb
    mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"
}

# Check dependencies
check_dependencies() {
    echo -e "${GREEN}Checking dependencies...${NC}"
    
    local missing=0
    
    # Check for dpkg-deb
    if ! command -v dpkg-deb &> /dev/null; then
        echo -e "${RED}Error: dpkg-deb not found.${NC}"
        echo "Install with: sudo apt-get install dpkg-dev"
        missing=1
    fi
    
    # Check for debhelper
    if ! command -v debhelper &> /dev/null; then
        echo -e "${RED}Error: debhelper not found.${NC}"
        echo "Install with: sudo apt-get install debhelper"
        missing=1
    fi
    
    # Check for dh-make
    if ! command -v dh &> /dev/null; then
        echo -e "${RED}Error: debhelper/dh not found.${NC}"
        echo "Install with: sudo apt-get install debhelper"
        missing=1
    fi
    
    # Check for fakeroot
    if ! command -v fakeroot &> /dev/null; then
        echo -e "${RED}Error: fakeroot not found.${NC}"
        echo "Install with: sudo apt-get install fakeroot"
        missing=1
    fi
    
    if [ $missing -ne 0 ]; then
        exit 1
    fi
    
    echo -e "${GREEN}All dependencies are installed.${NC}"
}

# Build the package
build_package() {
    echo -e "${GREEN}Building Debian package...${NC}"
    
    # Create build directory
    mkdir -p "$BUILD_DIR/$APP_NAME-$APP_VERSION"
    
    # Copy debian directory
    cp -r package/deb/debian "$BUILD_DIR/$APP_NAME-$APP_VERSION/"
    
    # Build the package
    cd "$BUILD_DIR/$APP_NAME-$APP_VERSION"
    
    echo -e "${GREEN}Running dpkg-buildpackage...${NC}"
    dpkg-buildpackage -us -uc -b 2>&1 | tail -20
    
    # Move the .deb file to output directory
    if [ -f "../${PACKAGE_NAME}.deb" ]; then
        mv "../${PACKAGE_NAME}.deb" "../../$OUTPUT_DIR/${PACKAGE_NAME}.deb"
        echo -e "${GREEN}Debian package created: $OUTPUT_DIR/${PACKAGE_NAME}.deb${NC}"
    else
        echo -e "${RED}Error: Debian package was not created.${NC}"
        exit 1
    fi
    
    cd ../../
}

# Main execution
main() {
    echo "=========================================="
    echo "Open Omniscience Debian Package Builder"
    echo "Version: $APP_VERSION"
    echo "=========================================="
    echo ""
    
    cleanup
    check_dependencies
    build_package
    
    echo ""
    echo "=========================================="
    echo -e "${GREEN}Debian package build complete!${NC}"
    echo ""
    echo "Output: $OUTPUT_DIR/${PACKAGE_NAME}.deb"
    echo ""
    echo "To install the package:"
    echo "  sudo dpkg -i dist/${PACKAGE_NAME}.deb"
    echo ""
    echo "To run the application:"
    echo "  open-omniscience"
    echo ""
    echo "Or from the terminal:"
    echo "  /usr/bin/open-omniscience"
    echo ""
    echo "Desktop launcher:"
    echo "  The package will automatically install a desktop launcher"
    echo "  to the user's desktop and applications menu during installation."
    echo ""
    echo "To manually install/remove desktop launcher after installation:"
    echo "  Install: /usr/share/open-omniscience/launcher/install-desktop-launcher.sh install"
    echo "  Remove:  /usr/share/open-omniscience/launcher/install-desktop-launcher.sh uninstall"
    echo "=========================================="
}

# Run main function
main "$@"
