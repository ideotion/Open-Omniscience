#!/bin/bash

# Build Open-Omniscience .deb package manually
# This script creates a .deb package without requiring dpkg-deb

set -e

PACKAGE_NAME="open-omniscience"
VERSION="0.02-1"
PACKAGE_DIR="/workspace/open-omniscience-deb"
BUILD_DIR="/workspace/open-omniscience-build"
OUTPUT_DIR="/workspace"
DEB_FILE="${PACKAGE_NAME}_${VERSION}_all.deb"

# Clean up previous builds
rm -rf "$BUILD_DIR" "$OUTPUT_DIR/$DEB_FILE"
mkdir -p "$BUILD_DIR"

# Create the data.tar.gz
cd "$PACKAGE_DIR"
echo "Creating data.tar.gz..."
tar -czf "$BUILD_DIR/data.tar.gz" -C "$PACKAGE_DIR" opt

# Create the control.tar.gz
cd "$PACKAGE_DIR/DEBIAN"
echo "Creating control.tar.gz..."
tar -czf "$BUILD_DIR/control.tar.gz" -C "$PACKAGE_DIR" DEBIAN

# Create the debian-binary file
echo "2.0" > "$BUILD_DIR/debian-binary"

# Build the .deb file using ar
cd "$BUILD_DIR"
echo "Building $DEB_FILE..."
ar rcs "$OUTPUT_DIR/$DEB_FILE" debian-binary control.tar.gz data.tar.gz

echo "Successfully created: $OUTPUT_DIR/$DEB_FILE"

# Clean up
rm -rf "$BUILD_DIR"

echo "Package built successfully!"
ls -lh "$OUTPUT_DIR/$DEB_FILE"
