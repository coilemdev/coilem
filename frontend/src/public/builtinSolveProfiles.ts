import noLoad from './examples/prius-2004-tutorial-bemf-v1.coilem?raw';
import loaded from './examples/prius-2004-loaded-torque-v1.coilem?raw';
import { parseDesignFile } from './designFile';
import { builtinProfiles } from './solveProfiles';

export const BUILTIN_SOLVE_PROFILES = builtinProfiles(parseDesignFile(noLoad).config, parseDesignFile(loaded).config);
