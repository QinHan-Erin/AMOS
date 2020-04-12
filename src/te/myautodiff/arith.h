
#ifndef TVM_TE_AUTODIFF_ARITH_H_
#define TVM_TE_AUTODIFF_ARITH_H_

#include <tvm/tir/expr.h>
#include <tvm/te/operation.h>
#include <vector>
#include <unordered_map>
#include <utility>

namespace tvm {
namespace te {

template<typename T>
class Matrix {
 public:
  Matrix(int height, int width) : width_(width), height_(height) {
    ptr = new T[width * height];
  }
  ~Matrix() {
    if (ptr != nullptr) {
      delete []ptr;
    }
  }

  int height() const {
    return height_;
  }

  int width() const {
    return width_;
  }

  T *operator[](int id) {
    CHECK(id < height_) << "index out of height range: " << id << " vs. " << height_ << "\n";
    return (ptr + id * width_);
  }

  void swap_row(int i, int j);

  void swap_col(int i, int j);

  void scale_row(int i, T factor);

  void scale_col(int j, T factor);

  void add_row(int i, int j, T factor);

  void add_col(int i, int j, T factor);

  void row_transform(int i, int j, T s, T t, T f, T g);

  void col_transform(int i, int j, T s, T t, T f, T g);

 private:
  T *ptr;
  int width_, height_;
};


enum class ExtRangeType : uint8_t {
  LORC,  // left open right close
  LORO,  // left open right open
  LCRO,  // left close right open
  LCRC   // left close right close
};


class ExtRange {
 public:
  PrimExpr left;
  PrimExpr right;
  bool left_inf;
  bool right_inf;

  ExtRange() { left_inf = true; right_inf = true; }

  ExtRange(ExtRange &range) : left(range.left), right(range.right),
    left_inf(range.left_inf), right_inf(range.right_inf) {}

  ExtRange(ExtRange &&range) : left(std::move(range.left)), right(std::move(range.right)),
    left_inf(std::move(range.left_inf)), right_inf(std::move(range.right_inf)) {}

  ExtRange(const ExtRange &range) : left(range.left), right(range.right),
    left_inf(range.left_inf), right_inf(range.right_inf) {}

  ExtRange(const ExtRange &&range) : left(std::move(range.left)), right(std::move(range.right)),
    left_inf(std::move(range.left_inf)), right_inf(std::move(range.right_inf)) {}

  ExtRange(PrimExpr l, PrimExpr r, bool li, bool ri) : left(l), right(r), left_inf(li), right_inf(ri) {}

  ExtRange &operator=(ExtRange &range) {
    left = range.left;
    right = range.right;
    left_inf = range.left_inf;
    right_inf = range.right_inf;
    return *this;
  }

  ExtRange &operator=(ExtRange &&range) {
    left = std::move(range.left);
    right = std::move(range.right);
    left_inf = std::move(range.left_inf);
    right_inf = std::move(range.right_inf);
    return *this;
  }

  ExtRange &operator=(const ExtRange &range) {
    left = range.left;
    right = range.right;
    left_inf = range.left_inf;
    right_inf = range.right_inf;
    return *this;
  }

  ExtRange &operator=(const ExtRange &&range) {
    left = std::move(range.left);
    right = std::move(range.right);
    left_inf = std::move(range.left_inf);
    right_inf = std::move(range.right_inf);
    return *this;
  }

  ExtRange floor_div(int factor);

  ExtRange floor_mod(int factor);

  ExtRangeType range_type() {
    if (left_inf && right_inf) {
      return ExtRangeType::LORO;
    } else if (left_inf && !right_inf) {
      return ExtRangeType::LORC;
    } else if (!left_inf && !right_inf) {
      return ExtRangeType::LCRC;
    } else {
      return ExtRangeType::LCRO;
    }
  }
};


// class RangeInference : public ExprFunctor<ExtRange(const PrimExpr&)> {
//  private:
//   std::vector<ExtRange> scope_;
//  public:
//   std::unoredered_map<std::string, ExtRange> range_map;
//   RangeInference(ExtRange init) { scope_.push_back(init); }

//  protected:
//   // list of functions to override.
//   ExtRange VisitExpr_(const VarNode* op) override {
//     range_map[op->name_hint] = scope_.back();
//     return scope_.back();
//   }

//   ExtRange VisitExpr_(const SizeVarNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const LoadNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const BufferLoadNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const LetNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const CallNode* op) override UNEXPECTED

//   ExtRange VisitExpr_(const AddNode* op) override {

//   }

//   ExtRange VisitExpr_(const SubNode* op) override {

//   }

//   ExtRange VisitExpr_(const MulNode* op) override {

//   }

//   ExtRange VisitExpr_(const DivNode* op) override {

//   }

//   ExtRange VisitExpr_(const ModNode* op) override {

//   }

//   ExtRange VisitExpr_(const FloorDivNode* op) override {

//   }

//   ExtRange VisitExpr_(const FloorModNode* op) override {

//   }

//   ExtRange VisitExpr_(const MinNode* op) override {

//   }

//   ExtRange VisitExpr_(const MaxNode* op) override {

//   }

//   ExtRange VisitExpr_(const EQNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const NENode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const LTNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const LENode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const GTNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const GENode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const AndNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const OrNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const ReduceNode* op) override UNEXPECTED

//   ExtRange VisitExpr_(const CastNode* op) override {
//     type_check(CastNode)
//     return VisitExpr(op->value, other_op->value);
//   }

//   ExtRange VisitExpr_(const NotNode* op) override UNEXPECTED

//   ExtRange VisitExpr_(const SelectNode* op) override {
//     type_check(SelectNode)
//     return (VisitExpr(op->condition, other_op->condition) &&
//             VisitExpr(op->true_value, other_op->true_value) &&
//             VisitExpr(op->false_value, other_op->false_value));
//   }

//   ExtRange VisitExpr_(const RampNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const BroadcastNode* op) override UNEXPECTED
//   ExtRange VisitExpr_(const ShuffleNode* op) override UNEXPECTED

//   ExtRange VisitExpr_(const IntImmNode* op) override {
//     type_check(IntImmNode)
//     return op->value == other_op->value;
//   }

//   ExtRange VisitExpr_(const FloatImmNode* op) override {
//     type_check(FloatImmNode)
//     return op->value == other_op->value;
//   }

//   ExtRange VisitExpr_(const StringImmNode* op) override {
//     type_check(StringImmNode)
//     return op->value == other_op->value;
//   }
// };


Array<PrimExpr> relax_matrix_array_product(Matrix<int> &m, Array<PrimExpr> &v);


bool check_identity(Matrix<int> &m, int dims);


bool divisible(int a, int b);


int ext_euclidean(int a, int b, int &x, int &y);


int smith_normalize(Matrix<int> &trans, Matrix<int> &U, Matrix<int> &V);


}  // namespace te
}  // namespace tvm
#endif  // TVM_TE_AUTODIFF_ARITH_H_
