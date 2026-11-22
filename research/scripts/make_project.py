#!/usr/bin/env python3
"""Regenerate the dependency-free Xcode project. No XcodeGen required."""
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
existing_path = ROOT / 'MagAir.xcodeproj/project.pbxproj'
existing = existing_path.read_text() if existing_path.exists() else ''
bundle_match = re.search(r'PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);', existing)
team_match = re.search(r'DEVELOPMENT_TEAM = ([^;]+);', existing)
bundle = bundle_match[1] if bundle_match else 'com.magair.research.collector'
team = team_match[1] if team_match else None
def uid(s):
    return hashlib.sha1(s.encode()).hexdigest()[:24].upper()
sources = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'MagAir').rglob('*.swift'))
resources = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'MagAir/Resources').glob('*.json'))
objects = []
def obj(key, body):
    objects.append(f'{uid(key)} = {{ {body} }};')
for source in sources:
    obj(source, f'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "{source}"; sourceTree = SOURCE_ROOT;')
    obj('build'+source, f'isa = PBXBuildFile; fileRef = {uid(source)};')
for resource in resources:
    obj(resource, f'isa = PBXFileReference; lastKnownFileType = text.json; path = "{resource}"; sourceTree = SOURCE_ROOT;')
    obj('build'+resource, f'isa = PBXBuildFile; fileRef = {uid(resource)};')
obj('product', 'isa = PBXFileReference; explicitFileType = wrapper.application; path = MagAir.app; sourceTree = BUILT_PRODUCTS_DIR;')
obj('products', f'isa = PBXGroup; children = ({uid("product")},); name = Products; sourceTree = "<group>";')
obj('group', f'isa = PBXGroup; children = ({",".join(uid(x) for x in sources+resources)},{uid("products")},); sourceTree = "<group>";')
obj('sources', f'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({",".join(uid("build"+x) for x in sources)},); runOnlyForDeploymentPostprocessing = 0;')
obj('frameworks', 'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
obj('resources', f'isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ({",".join(uid("build"+x) for x in resources)},); runOnlyForDeploymentPostprocessing = 0;')
for scope in ['project', 'target']:
    for config in ['Debug', 'Release']:
        settings = 'CLANG_ENABLE_MODULES = YES; SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 17.0; SWIFT_VERSION = 5.0;'
        if scope == 'target':
            settings += f' PRODUCT_NAME = MagAir; PRODUCT_BUNDLE_IDENTIFIER = {bundle}; TARGETED_DEVICE_FAMILY = 2; INFOPLIST_FILE = MagAir/Info.plist; CODE_SIGN_STYLE = Automatic; GENERATE_INFOPLIST_FILE = NO; SUPPORTED_PLATFORMS = "iphoneos iphonesimulator"; SUPPORTS_MACCATALYST = NO; SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD = NO; SWIFT_EMIT_LOC_STRINGS = YES;'
            if team:
                settings += f' DEVELOPMENT_TEAM = {team};'
        if config == 'Debug':
            settings += ' SWIFT_OPTIMIZATION_LEVEL = "-Onone"; DEBUG_INFORMATION_FORMAT = dwarf; SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;'
        else:
            settings += ' SWIFT_OPTIMIZATION_LEVEL = "-O"; DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym"; SWIFT_COMPILATION_MODE = wholemodule;'
        obj(scope+config, f'isa = XCBuildConfiguration; buildSettings = {{ {settings} }}; name = {config};')
    obj(scope+'configs', f'isa = XCConfigurationList; buildConfigurations = ({uid(scope+"Debug")},{uid(scope+"Release")},); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
obj('target', f'isa = PBXNativeTarget; buildConfigurationList = {uid("targetconfigs")}; buildPhases = ({uid("sources")},{uid("frameworks")},{uid("resources")},); buildRules = (); dependencies = (); name = MagAir; productName = MagAir; productReference = {uid("product")}; productType = "com.apple.product-type.application";')
obj('project', f'isa = PBXProject; attributes = {{ LastUpgradeCheck = 2620; TargetAttributes = {{ {uid("target")} = {{ CreatedOnToolsVersion = 26.2; }}; }}; }}; buildConfigurationList = {uid("projectconfigs")}; compatibilityVersion = "Xcode 14.0"; developmentRegion = ko; hasScannedForEncodings = 0; knownRegions = (ko,en,Base,); mainGroup = {uid("group")}; productRefGroup = {uid("products")}; projectDirPath = ""; projectRoot = ""; targets = ({uid("target")},);')
project = ROOT / 'MagAir.xcodeproj'
project.mkdir(exist_ok=True)
(project / 'project.pbxproj').write_text('// !$*UTF8*$!\n{ archiveVersion = 1; classes = {}; objectVersion = 56; objects = {\n'+'\n'.join(objects)+f'\n}}; rootObject = {uid("project")}; }}\n')
scheme = f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2620" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid('target')}" BuildableName="MagAir.app" BlueprintName="MagAir" ReferencedContainer="container:MagAir.xcodeproj"/></BuildActionEntry></BuildActionEntries></BuildAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0"><BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid('target')}" BuildableName="MagAir.app" BlueprintName="MagAir" ReferencedContainer="container:MagAir.xcodeproj"/></BuildableProductRunnable></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"/>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>'''
scheme_dir = project / 'xcshareddata/xcschemes'
scheme_dir.mkdir(parents=True, exist_ok=True)
(scheme_dir / 'MagAir.xcscheme').write_text(scheme)
print(f'Generated MagAir.xcodeproj with {len(sources)} Swift files')
