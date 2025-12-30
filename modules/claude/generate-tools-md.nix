{ lib }:

{ packages }:

let
  # Extract metadata from packages
  packageItems = builtins.map (pkg:
    let
      name = pkg.pname or pkg.name or "unknown";
      meta = pkg.meta or {};
    in {
      inherit name;
      description = meta.description or "No description available";
      homepage = meta.homepage or null;
      mainProgram = meta.mainProgram or null;
    }
  ) packages;

  allItems = packageItems;

  # Sort items alphabetically by name
  sortedItems = builtins.sort (a: b: a.name < b.name) allItems;

  # Format a single package entry
  formatItem = item: let
    hasHomepage = item.homepage != null;
    hasMainProgram = item.mainProgram != null;

    # Detect if homepage is a local source file (contains .bash, .nix, or starts with /)
    isSourceFile = hasHomepage && (
      (builtins.match ".*\\.(bash|nix).*" item.homepage) != null ||
      (builtins.match "/.*" item.homepage) != null
    );

    homepageLabel = if isSourceFile then "Source File" else "Homepage";

    # Build lines conditionally to avoid extra blank lines
    lines = lib.filter (line: line != "") [
      "### ${item.name}"
      ""
      "**Description:** ${item.description}"
      (lib.optionalString hasMainProgram "**Command:** `${item.mainProgram}`")
      (lib.optionalString hasHomepage "**${homepageLabel}:** ${item.homepage}")
    ];
  in lib.concatStringsSep "\n" lines;

in
''
# Available Tools & Utilities

*Auto-generated from Home Manager package list using built-in package metadata.*

---

${lib.concatMapStringsSep "\n\n---\n\n" formatItem sortedItems}

---

*Generated from: home.packages*
''
