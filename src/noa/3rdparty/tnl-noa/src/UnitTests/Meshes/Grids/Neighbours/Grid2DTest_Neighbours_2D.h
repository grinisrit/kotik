
#pragma once

#ifdef HAVE_GTEST

#include "Grid2DTestSuite.h"
#include <gtest/gtest.h>

TYPED_TEST_SUITE(GridTestSuite, Implementations);

TYPED_TEST(GridTestSuite, TestNeighbour_OF_2D_Entity_TO_0D_By_DynamicGetter) {
   // EntityDimension | NeighbourEntityDimension | Orientation
   for (const auto& dimension : this->dimensions) {
      testDynamicNeighbourEntityGetterForAllStencils<TypeParam, 2, 0>(this -> grid, dimension);
      testDynamicNeighbourEntityGetterForAllStencils<TypeParam, 2, 0, 0>(this -> grid, dimension);
   }
}

TYPED_TEST(GridTestSuite, TestNeighbour_OF_2D_Entity_TO_1D_By_DynamicGetter) {
   // EntityDimension | NeighbourEntityDimension | Orientation
   for (const auto& dimension : this->dimensions) {
      testDynamicNeighbourEntityGetterForAllStencils<TypeParam, 2, 1>(this -> grid, dimension);

      testDynamicNeighbourEntityGetterForAllStencils<TypeParam, 2, 1, 0>(this -> grid, dimension);
      testDynamicNeighbourEntityGetterForAllStencils<TypeParam, 2, 1, 1>(this -> grid, dimension);
   }
}

TYPED_TEST(GridTestSuite, TestNeighbour_OF_2D_Entity_TO_2D_By_DynamicGetter) {
   // EntityDimension | NeighbourEntityDimension | Orientation
   for (const auto& dimension : this->dimensions) {
      testDynamicNeighbourEntityGetterForAllStencils<TypeParam, 2, 2>(this -> grid, dimension);

      testDynamicNeighbourEntityGetterForAllStencils<TypeParam, 2, 2, 0>(this -> grid, dimension);
   }
}

#endif

#include "../../../main.h"
